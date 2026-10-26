// Subordinate transport of omi-launcher.ps1 / run-service-logged.ps1, not a manager.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Net;

namespace Omi.OwnedShutdown {
    // One operation clock, created on acceptance and passed through every layer.
    // The shorter constructor is internal and used only by isolated fixtures.
    public sealed class LifecycleDeadline {
        readonly Stopwatch clock = Stopwatch.StartNew();
        readonly int budget;
        public readonly string AcceptedAt = DateTime.UtcNow.ToString("o");
        public LifecycleDeadline() : this(180000) { }
        internal LifecycleDeadline(int milliseconds) { budget = milliseconds; }
        public int RemainingMilliseconds { get { return (int)Math.Max(0, budget - clock.ElapsedMilliseconds); } }
        public long ElapsedMilliseconds { get { return clock.ElapsedMilliseconds; } }
    }

    internal static class Wire {
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 8192 };
        public static string Encode(Dictionary<string,string> value) { return Json.Serialize(value); }
        public static Dictionary<string,string> Decode(string line) {
            if (line == null || line.Length > 8192) throw new IOException("CHANNEL_CLOSED_OR_OVERSIZE");
            try {
                var value = Json.Deserialize<Dictionary<string,string>>(line);
                if (value == null) throw new IOException("CHANNEL_INVALID");
                return value;
            } catch { throw new IOException("CHANNEL_INVALID"); }
        }
        public static string Created(Process p) { return p.StartTime.ToUniversalTime().ToFileTimeUtc().ToString(); }
        public static long Now { get { return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(); } }
        public static string Nonce() {
            var bytes = new byte[32]; using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(bytes);
            return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
        }
        public static Dictionary<string,string> Copy(Dictionary<string,string> value, string state) {
            var result = new Dictionary<string,string>(value); result["state"] = state; return result;
        }
        public static bool Same(Dictionary<string,string> a, Dictionary<string,string> b, params string[] keys) {
            foreach (var key in keys) if (!a.ContainsKey(key) || !b.ContainsKey(key) || a[key] != b[key]) return false;
            return true;
        }
        public static readonly string[] Identity = {"instance", "nonce", "launcher_pid", "launcher_created", "runner_pid", "runner_created", "child_pid", "child_created"};
        public static bool Rearmed(Dictionary<string,string> request, Dictionary<string,string> receipt) {
            long deadline;
            return Same(request, receipt, Identity) && Same(request, receipt, "request_id", "deadline") &&
                receipt.ContainsKey("state") && receipt["state"] == "PREFLIGHT_REARMED" &&
                receipt.ContainsKey("rearmed") && receipt["rearmed"] == "true" &&
                Int64.TryParse(request["deadline"], out deadline) && deadline > Now;
        }
        public static void Send(StreamWriter writer, Dictionary<string,string> value) { writer.WriteLine(Encode(value)); writer.Flush(); }
        public static Dictionary<string,string> Read(StreamReader reader, int milliseconds) {
            var task = reader.ReadLineAsync();
            if (!task.Wait(milliseconds)) throw new TimeoutException("CHANNEL_TIMEOUT");
            return Decode(task.Result);
        }
        public static int Remaining(long deadline, Stopwatch clock, long budget, int maximum = 10000) {
            long left = Math.Min(deadline - Now, budget - clock.ElapsedMilliseconds);
            if (left <= 0) throw new TimeoutException("STOP_DEADLINE_EXCEEDED");
            return (int)Math.Min(left, maximum);
        }
        public static string Quote(string value) {
            if (value.Contains("\"") || value.EndsWith("\\")) throw new ArgumentException("INVALID_FIXED_PATH");
            return "\"" + value + "\"";
        }
        public static void PrivateDirectory(string path, bool create) {
            for (var node = new DirectoryInfo(path); node != null; node = node.Parent)
                if (node.Exists && (node.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("REPARSE_POINT_REFUSED");
            var sid = WindowsIdentity.GetCurrent().User;
            if (create) {
                if (Directory.Exists(path)) throw new IOException("FRESH_DIRECTORY_REQUIRED");
                var security = new DirectorySecurity(); security.SetOwner(sid); security.SetAccessRuleProtection(true, false);
                security.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
                    InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
                Directory.CreateDirectory(path, security);
            }
            var acl = Directory.GetAccessControl(path);
            if (!acl.AreAccessRulesProtected) throw new IOException("PROTECTED_ACL_REQUIRED");
            if (!sid.Equals(acl.GetOwner(typeof(SecurityIdentifier)))) throw new IOException("PRIVATE_OWNER_REQUIRED");
            bool own = false;
            foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier))) {
                if (rule.AccessControlType != AccessControlType.Allow) continue;
                if (!sid.Equals(rule.IdentityReference)) throw new IOException("PRIVATE_ACL_REQUIRED");
                if ((rule.FileSystemRights & FileSystemRights.FullControl) == FileSystemRights.FullControl) own = true;
            }
            if (!own) throw new IOException("PRIVATE_ACL_REQUIRED");
        }
        public static Process Start(string file, string args, string cwd, bool redirectError = false) {
            Process retained;
            Start(file, args, cwd, out retained, redirectError);
            return retained;
        }
        public static void Start(string file, string args, string cwd, out Process retained, bool redirectError = false) {
            var info = new ProcessStartInfo(file, args) { WorkingDirectory = cwd, UseShellExecute = false,
                CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = redirectError };
            retained = Process.Start(info); var handle = retained.Handle;
        }
    }

    // Executed only inside the existing mutex-owning Launcher. The private
    // inherited channel is constructed at birth; existing PIDs cannot be adopted.
    public sealed class ProductionSession : IDisposable {
        readonly Process runner;
        readonly Process child;
        readonly Dictionary<string,string> identity;
        readonly string repo;
        readonly string release;
        readonly string host;
        readonly int port;
        public string PythonExecutable { get; private set; }
        bool terminal;
        readonly object stopGate = new object();
        readonly Dictionary<string,StopEvidence> stops = new Dictionary<string,StopEvidence>();
        public StopEvidence LastStop { get; private set; }
        Dictionary<string,string> confirmedStopReceipt;
        Dictionary<string,string> failedStartupReceipt;
        bool failedStartRecoveryAttempted;
        bool retirementAttempted;
        Task<StopEvidence> boundedStop;
        volatile bool cutoffStarted;
        StopEvidence forcedStop;
        DateTime readinessVerifiedAt;
        DateTime startReadinessVerifiedAt;
        public Process RunnerProcess { get { return runner; } }
        public int ChildPid { get { return child == null ? 0 : child.Id; } }
        public string ChildCreated { get { return child == null ? null : child.StartTime.ToUniversalTime().ToString("o"); } }
        public string StartupFailure { get; private set; }
        public bool StartupExitConfirmed { get; private set; }
        public string ReleaseId { get { return release; } }
        public string SelectedHost { get { return host; } }
        public int SelectedPort { get { return port; } }
        public bool Terminal { get { return terminal; } }
        public bool HasRetainedIdentity { get { return RetainedIdentityMatches(); } }
        public string RestartBlocker { get { return identity.ContainsKey("restart_blocker") ? identity["restart_blocker"] : "NONTERMINAL_WRITER_PREFLIGHT_UNAVAILABLE"; } }
        public bool ReadinessVerified { get { return Alive && (DateTime.UtcNow - readinessVerifiedAt).TotalSeconds < 5; } }
        public bool StartReadinessVerified { get { return !terminal && String.IsNullOrEmpty(StartupFailure) &&
            ReadinessVerified && (DateTime.UtcNow - startReadinessVerifiedAt).TotalSeconds < 5; } }
        public bool Alive {
            get {
                try {
                    using (var owner = Process.GetCurrentProcess())
                        return child != null && identity != null && !runner.HasExited && !child.HasExited &&
                            owner.Id.ToString() == identity["launcher_pid"] && Wire.Created(owner) == identity["launcher_created"] &&
                            child.Id.ToString() == identity["child_pid"] && Wire.Created(child) == identity["child_created"] &&
                            runner.Id.ToString() == identity["runner_pid"] && Wire.Created(runner) == identity["runner_created"];
                } catch { return false; }
            }
        }
        public static string ApplicationRelease(string repo) {
            var paths = Directory.GetFiles(Path.Combine(repo, "backend", "app"), "*.py", SearchOption.AllDirectories);
            Array.Sort(paths, (left, right) => StringComparer.Ordinal.Compare(left.Replace('\\', '/'), right.Replace('\\', '/')));
            using (var bytes = new MemoryStream()) using (var sha = SHA256.Create()) {
                foreach (var path in paths) {
                    RejectReparse(path);
                    var name = path.Substring(repo.TrimEnd('\\').Length + 1).Replace('\\', '/');
                    var label = Encoding.UTF8.GetBytes(name + "\0");
                    bytes.Write(label, 0, label.Length);
                    var hash = sha.ComputeHash(File.ReadAllBytes(path)); bytes.Write(hash, 0, hash.Length);
                }
                return BitConverter.ToString(sha.ComputeHash(bytes.ToArray())).Replace("-", "").ToLowerInvariant();
            }
        }
        public static void RejectReparse(string path) {
            var full = Path.GetFullPath(path);
            if (!Path.IsPathRooted(path) || full != path || path.StartsWith(@"\\")) throw new IOException("LOCAL_CANONICAL_PATH_REQUIRED");
            for (var current = full; !String.IsNullOrEmpty(current); current = Path.GetDirectoryName(current))
                if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new IOException("REPARSE_POINT_REFUSED");
        }
        public static string FixedPython(string repo) {
            var config = Path.Combine(repo, ".venv", "pyvenv.cfg"); RejectReparse(config);
            string executable = null;
            foreach (var line in File.ReadAllLines(config)) {
                if (!line.StartsWith("executable = ", StringComparison.Ordinal)) continue;
                if (executable != null) throw new IOException("INTERPRETER_CONFIG_AMBIGUOUS");
                executable = line.Substring(13);
            }
            if (executable == null) throw new IOException("INTERPRETER_CONFIG_MISSING");
            RejectReparse(executable);
            return executable;
        }
        public static ProductionSession Start(string repo, string store, string host, int port) {
            return Start(repo, store, host, port, null);
        }
        public static ProductionSession Start(string repo, string store, string host, int port, string expectedRelease) {
            return new ProductionSession(repo, store, host, port, expectedRelease);
        }
        internal static void RequireRelease(string repo, string expectedRelease) {
            if (String.IsNullOrEmpty(expectedRelease) || ApplicationRelease(repo) != expectedRelease)
                throw new IOException("RESTART_SOURCE_CHANGED");
        }
        ProductionSession(string repository, string store, string selectedHost, int selectedPort, string expectedRelease) {
            repo = Path.GetFullPath(repository); host = selectedHost; port = selectedPort;
            if ((host != "127.0.0.1" && host != "::1") || port < 1 || port > 65535) throw new IOException("FIXED_ENDPOINT_REQUIRED");
            RejectReparse(repo); Wire.PrivateDirectory(store, false);
            var owner = Process.GetCurrentProcess();
            if (Environment.GetEnvironmentVariable("OMI_RUNTIME_LAUNCHER_PID") != owner.Id.ToString() ||
                Environment.GetEnvironmentVariable("OMI_RUNTIME_LAUNCHER_CREATED") != Wire.Created(owner)) throw new IOException("LAUNCHER_CONTEXT_REQUIRED");
            var python = FixedPython(repo); PythonExecutable = python;
            release = ApplicationRelease(repo);
            if (expectedRelease != null && release != expectedRelease) throw new IOException("RESTART_SOURCE_CHANGED");
            var root = Path.Combine(store, "sessions", Guid.NewGuid().ToString("N"));
            Wire.PrivateDirectory(root, true);
            var boot = new Dictionary<string,string> { {"scope", "PRODUCTION"}, {"instance", Guid.NewGuid().ToString()},
                {"nonce", Wire.Nonce()}, {"launcher_pid", owner.Id.ToString()}, {"launcher_created", Wire.Created(owner)},
                {"journal", root}, {"host", host}, {"port", port.ToString()}, {"release_id", release} };
            identity = boot;
            try {
            Wire.Start(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell\\v1.0\\powershell.exe"),
                "-NoProfile -File " + Wire.Quote(Path.Combine(repo, "scripts", "run-service-logged.ps1")) +
                " -OwnedShutdownChannel -ServiceName backend -RepoRoot " + Wire.Quote(repo) +
                " -WorkingDirectory " + Wire.Quote(Path.Combine(repo, "backend")) + " -FilePath " + Wire.Quote(python) +
                " -ArgumentsJsonBase64 W10= -LauncherPid " + owner.Id, repo, out runner);
            boot["runner_pid"] = runner.Id.ToString(); boot["runner_created"] = Wire.Created(runner);
            Wire.Send(runner.StandardInput, boot);
            var startupClock = Stopwatch.StartNew();
            var frame = Wire.Read(runner.StandardOutput, 100000);
            if (!Wire.Same(boot, frame, "instance", "nonce", "launcher_pid", "launcher_created", "runner_pid", "runner_created", "host", "port", "release_id"))
                throw new IOException("OWNED_READY_MISMATCH");
            if (frame["state"] == "STARTING") {
                identity = frame;
                // Failure before READY can still have exact exit evidence from
                // Runner's retained child handle. Retain ours when still alive.
                try {
                    child = Process.GetProcessById(Int32.Parse(frame["child_pid"])); var handle = child.Handle;
                    if (Wire.Created(child) != frame["child_created"]) { child.Dispose(); child = null; }
                } catch { child = null; }
                frame = Wire.Read(runner.StandardOutput, Math.Max(1, 100000 - (int)startupClock.ElapsedMilliseconds));
            }
            if (ConfirmStartupExit(frame)) return;
            identity = frame;
            if (!Wire.Same(boot, identity, "instance", "nonce", "launcher_pid", "launcher_created", "runner_pid", "runner_created", "host", "port", "release_id") ||
                identity["state"] != "READY" || identity["loaded_release_identity"] != "APPLICATION_SOURCE_SNAPSHOT") throw new IOException("OWNED_READY_MISMATCH");
            if (child == null) { child = Process.GetProcessById(Int32.Parse(identity["child_pid"])); var retained = child.Handle; }
            if (!Alive || ApplicationRelease(repo) != release) throw new IOException("SOURCE_OR_IDENTITY_CHANGED");
            } catch {
                // Return the retained owner object even on ambiguous startup.
                // The existing Launcher keeps this handle and never retries.
                StartupFailure = "OWNED_START_UNKNOWN"; terminal = true;
            }
        }
        bool ConfirmStartupExit(Dictionary<string,string> receipt) {
            if (!Wire.Same(identity, receipt, "instance", "nonce", "launcher_pid", "launcher_created", "runner_pid", "runner_created", "host", "port", "release_id") ||
                !receipt.ContainsKey("state") || receipt["state"] != "START_FAILED" ||
                !receipt.ContainsKey("reason") || receipt["reason"] != "OWNED_START_EXIT_CONFIRMED") return false;
            if (identity.ContainsKey("child_pid")) {
                if (!Wire.Same(identity, receipt, "child_pid", "child_created") ||
                    !receipt.ContainsKey("child_exact_exit") || receipt["child_exact_exit"] != "true") return false;
                int exitCode;
                if (!receipt.ContainsKey("child_exit_code") || !Int32.TryParse(receipt["child_exit_code"], out exitCode)) return false;
                if (child != null && (!child.WaitForExit(1000) || child.ExitCode != exitCode)) return false;
            } else if (!receipt.ContainsKey("child_started") || receipt["child_started"] != "false") return false;
            if (!runner.WaitForExit(2000) || runner.ExitCode != 79) return false;
            failedStartupReceipt = new Dictionary<string,string>(receipt);
            StartupExitConfirmed = true; StartupFailure = "OWNED_START_EXIT_CONFIRMED"; terminal = true;
            return true; // Startup failure, never a successful StopEvidence.
        }
        public bool RefreshStartupExit() {
            // No new read/command and no port inference. A startup timeout may
            // converge later only from the originally retained exact handles.
            if (StartupExitConfirmed) return true;
            if (StartupFailure != "OWNED_START_UNKNOWN" || child == null) return false;
            try {
                if (!Wire.Same(identity, new Dictionary<string,string> {
                    {"child_pid", child.Id.ToString()}, {"child_created", Wire.Created(child)},
                    {"runner_pid", runner.Id.ToString()}, {"runner_created", Wire.Created(runner)} },
                    "child_pid", "child_created", "runner_pid", "runner_created") ||
                    !child.HasExited || !runner.HasExited || runner.ExitCode != 79) return false;
                // ExitCode forces the OS exit evidence read; zero is not
                // required for a failed startup and is never Safe Stop proof.
                var exitCode = child.ExitCode;
                StartupExitConfirmed = true; StartupFailure = "OWNED_START_EXIT_CONFIRMED";
                return true;
            } catch { return false; }
        }
        public bool VerifyReadiness() {
            return VerifyReadiness(2500);
        }
        Dictionary<string,object> ReadEndpoint(string path, int timeout) {
            if (timeout <= 0) throw new TimeoutException("READINESS_TIMEOUT");
            var url = "http://" + (host == "::1" ? "[::1]" : host) + ":" + port + path;
            var request = (HttpWebRequest)WebRequest.Create(url);
            request.Proxy = null; request.AllowAutoRedirect = false;
            request.Timeout = timeout; request.ReadWriteTimeout = timeout;
            // Bound the entire response, including a slowly streaming body.
            using (var deadline = new Timer(_ => request.Abort(), null, timeout, Timeout.Infinite))
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var reader = new StreamReader(response.GetResponseStream())) {
                if (response.StatusCode != HttpStatusCode.OK) throw new IOException("READINESS_HTTP_FAILED");
                var buffer = new char[16385]; var length = reader.ReadBlock(buffer, 0, buffer.Length);
                if (length > 16384) throw new IOException("READINESS_OVERSIZE");
                return new JavaScriptSerializer { MaxJsonLength = 16384 }
                    .Deserialize<Dictionary<string,object>>(new string(buffer, 0, length));
            }
        }
        bool VerifyReadiness(int timeout) {
            if (!Alive) return false;
            return VerifyLoadedReadiness(ReadEndpoint("/api/system/runtime-control/status", timeout));
        }
        // The retained process attests its birth release, not today's disk image.
        // Disk adoption is checked separately at START and throughout restart.
        bool VerifyLoadedReadiness(Dictionary<string,object> value) {
            if (!Alive) return false;
            {
                var serving = value["serving_backend"] as Dictionary<string,object>;
                if (serving == null || !Object.Equals(serving["runtime_started"], true)) return false;
                var owned = serving["owned_start"] as Dictionary<string,object>;
                if (owned == null) return false;
                foreach (var key in new[] { "child_pid", "child_created", "instance", "host", "port", "release_id" })
                    if (!owned.ContainsKey(key) || !Object.Equals(owned[key], identity[key])) return false;
                if (!Alive) return false;
                readinessVerifiedAt = DateTime.UtcNow;
                return true;
            }
        }
        public Task<bool> WaitForStartReadinessAsync(int timeoutMilliseconds) {
            if (timeoutMilliseconds <= 0 || timeoutMilliseconds > 30000) throw new ArgumentOutOfRangeException("timeoutMilliseconds");
            return Task.Run(() => {
                startReadinessVerifiedAt = DateTime.MinValue;
                var clock = Stopwatch.StartNew();
                Func<int> remaining = () => (int)Math.Max(0, timeoutMilliseconds - clock.ElapsedMilliseconds);
                while (remaining() > 0 && !terminal && String.IsNullOrEmpty(StartupFailure) && Alive) {
                    try {
                        // readyz has no identity field. Bracket its real response
                        // with this instance's authenticated startup projection.
                        if (ApplicationRelease(repo) == release && VerifyReadiness(Math.Min(2500, remaining()))) {
                            var ready = ReadEndpoint("/api/system/readyz", Math.Min(2500, remaining()));
                            var checks = ready["checks"] as Dictionary<string,object>;
                            if (Object.Equals(ready["status"], "ready") && checks != null &&
                                Object.Equals(checks["runtime"], "ok") && Object.Equals(checks["database"], "ok") &&
                                VerifyReadiness(Math.Min(2500, remaining())) && ApplicationRelease(repo) == release && remaining() > 0) {
                                startReadinessVerifiedAt = DateTime.UtcNow;
                                return true;
                            }
                        }
                    } catch { /* observation only; never retry a start or stop */ }
                    Thread.Sleep(Math.Min(100, remaining()));
                }
                return false;
            });
        }
        // Distinct from StopEvidence. Late exit observation alone cannot grant
        // recovery: require the original runner receipt and both birth handles.
        public bool CanRecoverFailedStart {
            get {
                lock (stopGate) {
                    try {
                        if (failedStartRecoveryAttempted || retirementAttempted || !terminal ||
                            StartupFailure != "OWNED_START_EXIT_CONFIRMED" || !StartupExitConfirmed ||
                            LastStop != null || stops.Count != 0 || boundedStop != null || cutoffStarted ||
                            forcedStop != null || confirmedStopReceipt != null || failedStartupReceipt == null ||
                            readinessVerifiedAt != DateTime.MinValue || startReadinessVerifiedAt != DateTime.MinValue ||
                            !RetainedIdentityMatches() || !child.WaitForExit(0) || !runner.WaitForExit(0) ||
                            runner.ExitCode != 79 || child.ExitCode == 0 ||
                            !Wire.Same(identity, failedStartupReceipt, Wire.Identity) ||
                            !Wire.Same(identity, failedStartupReceipt, "host", "port", "release_id", "journal") ||
                            failedStartupReceipt["state"] != "START_FAILED" ||
                            failedStartupReceipt["reason"] != "OWNED_START_EXIT_CONFIRMED" ||
                            failedStartupReceipt["child_exact_exit"] != "true" ||
                            failedStartupReceipt["child_exit_code"] != child.ExitCode.ToString()) return false;
                        // No missing/rebuilt/edited receipt, uncertain persistence, or ACL bypass.
                        Wire.PrivateDirectory(identity["journal"], false);
                        var path = Path.Combine(identity["journal"], "startup-failure.json");
                        RejectReparse(path);
                        if (new FileInfo(path).Length > 8192) return false;
                        var persisted = Wire.Decode(File.ReadAllText(path));
                        if (persisted.Count != failedStartupReceipt.Count) return false;
                        foreach (var item in failedStartupReceipt)
                            if (!persisted.ContainsKey(item.Key) || persisted[item.Key] != item.Value) return false;
                        return true;
                    } catch { return false; }
                }
            }
        }
        public void RetireFailedStart(string requestId, string expectedRelease) {
            lock (stopGate) {
                Guid request;
                if (!Guid.TryParseExact(requestId, "D", out request) || requestId == identity["instance"] ||
                    stops.ContainsKey(requestId)) throw new InvalidOperationException("FAILED_START_RECOVERY_REPLAY");
                if (!CanRecoverFailedStart) throw new InvalidOperationException("FAILED_START_RECOVERY_NOT_ATTESTED");
                RequireRelease(repo, expectedRelease);
                // Consume before any IO/disposal. An uncertain write cannot be retried.
                failedStartRecoveryAttempted = true; retirementAttempted = true;
                var intent = Wire.Copy(identity, "FAILED_START_RECOVERY_INTENT");
                intent["request_id"] = requestId; intent["target_release_id"] = expectedRelease;
                intent["reason"] = "MANUAL_FAILED_START_RECOVERY";
                intent["accepted_at"] = DateTime.UtcNow.ToString("o");
                intent["startup_failure"] = StartupFailure;
                intent["child_exit_code"] = child.ExitCode.ToString();
                intent["runner_exit_code"] = runner.ExitCode.ToString();
                Runner.Persist(identity["journal"], "failed-start-recovery.json", intent);
                Dispose(); // StartupFailure and both original receipts remain unchanged.
            }
        }
        public bool CanStartAfterStop {
            get {
                lock (stopGate) {
                    try {
                        if (forcedStop != null) return !retirementAttempted && terminal &&
                            Object.ReferenceEquals(LastStop, forcedStop) && forcedStop.ForcedExitConfirmed &&
                            RetainedIdentityMatches() && child.WaitForExit(0) && runner.WaitForExit(0);
                        StopEvidence retained;
                        if (retirementAttempted || !terminal || !String.IsNullOrEmpty(StartupFailure) || LastStop == null ||
                            LastStop.State != "stopped" || LastStop.Reason != "LIFESPAN_AND_EXACT_EXIT" ||
                            !LastStop.ExactExit || LastStop.Rearmed || confirmedStopReceipt == null ||
                            !stops.TryGetValue(LastStop.RequestId, out retained) || !Object.ReferenceEquals(retained, LastStop) ||
                            !Wire.Same(identity, confirmedStopReceipt, Wire.Identity) ||
                            confirmedStopReceipt["request_id"] != LastStop.RequestId ||
                            confirmedStopReceipt["state"] != "SUCCEEDED_PRODUCTION" ||
                            confirmedStopReceipt["reason"] != "LIFESPAN_AND_EXACT_EXIT" ||
                            confirmedStopReceipt["no_respawn"] != "true") return false;
                        using (var owner = Process.GetCurrentProcess()) {
                            if (owner.Id.ToString() != identity["launcher_pid"] || Wire.Created(owner) != identity["launcher_created"]) return false;
                        }
                        // Original retained handles only, never PID lookup or port disappearance.
                        return child != null && runner != null && LastStop.BeforePid == child.Id &&
                            LastStop.BeforeCreated == ChildCreated && child.Id.ToString() == identity["child_pid"] &&
                            Wire.Created(child) == identity["child_created"] && runner.Id.ToString() == identity["runner_pid"] &&
                            Wire.Created(runner) == identity["runner_created"] &&
                            child.WaitForExit(0) && child.ExitCode == 0 && runner.WaitForExit(0) && runner.ExitCode == 0;
                    } catch { return false; }
                }
            }
        }
        public void DisposeAfterConfirmedStop() {
            lock (stopGate) {
                if (!CanStartAfterStop) throw new InvalidOperationException("PREVIOUS_EXACT_STOP_NOT_ATTESTED");
                // A partial Dispose cannot authorize another attempt. LastStop,
                // receipt and identities remain in the Launcher's retired list.
                retirementAttempted = true;
                Dispose();
            }
        }
        public sealed class StopEvidence {
            public string RequestId { get; internal set; }
            public int BeforePid { get; internal set; }
            public string BeforeCreated { get; internal set; }
            public string State { get; internal set; }
            public string Reason { get; internal set; }
            public bool ExactExit { get; internal set; }
            public bool Rearmed { get; internal set; }
            public bool StopNotSent { get; internal set; }
            public string PreflightStage { get; internal set; }
            public bool Forced { get; internal set; }
            public bool ForcedExitConfirmed { get; internal set; }
            public string CutoffAt { get; internal set; }
            public string AcceptedAt { get; internal set; }
            public long ElapsedMilliseconds { get; internal set; }
            public int RunnerPid { get; internal set; }
            public string RunnerCreated { get; internal set; }
            public string ProcessGeneration { get; internal set; }
            public string GracefulReason { get; internal set; }
            public string RecoveryState { get; internal set; }
            public string ReceiptPersistence { get; internal set; }
            internal StopEvidence() { }
        }
        public StopEvidence Stop(string requestId) {
            return Stop(requestId, null);
        }
        StopEvidence Stop(string requestId, string targetRelease) {
            Guid.ParseExact(requestId, "D");
            lock (stopGate) {
                StopEvidence previous;
                if (stops.TryGetValue(requestId, out previous)) return previous;
                // Terminal/unknown delivery never permits a new command or UUID.
                if (terminal && LastStop != null) return LastStop;
                var evidence = StopOnce(requestId, targetRelease);
                stops.Add(requestId, evidence);
                LastStop = evidence;
                return evidence;
            }
        }
        public Task<StopEvidence> StopAsync(string requestId) {
            return StopWithinDeadlineAsync(requestId, null, new LifecycleDeadline());
        }
        string schemaRequest;
        bool schemaFromFailedStart;
        bool schemaWorkerAttempted;
        bool schemaStopPending;
        HashSet<string> schemaRequests = new HashSet<string>();
        public bool SchemaWorkerSettled { get; private set; }
        public bool SchemaWorkerNoChange { get; private set; }
        public bool CanResumeAfterSchemaStopRefusal {
            get { lock (stopGate) {
                StopEvidence retained;
                return !schemaStopPending && !terminal && Alive && RetainedIdentityMatches() && boundedStop == null && !cutoffStarted &&
                    !schemaWorkerAttempted && LastStop != null && LastStop.State == "blocked" &&
                    (LastStop.Rearmed || LastStop.StopNotSent) && !LastStop.ExactExit &&
                    stops.TryGetValue(LastStop.RequestId, out retained) && Object.ReferenceEquals(retained, LastStop);
            } }
        }
        void AdmitSchemaRequest(string requestId) {
            if (schemaRequests == null) schemaRequests = new HashSet<string>();
            if (schemaStopPending || schemaRequests.Contains(requestId) || requestId == identity["instance"] ||
                (schemaRequest != null && schemaWorkerAttempted && (!SchemaWorkerSettled || !SchemaWorkerNoChange)))
                throw new IOException("SCHEMA_ADMISSION_NOT_ATTESTED");
            schemaRequests.Add(requestId); schemaRequest = requestId;
            schemaWorkerAttempted = false; SchemaWorkerSettled = false; SchemaWorkerNoChange = false;
        }
        public void AdmitFailedStartSchemaMaintenance(string requestId, string targetRelease) {
            lock (stopGate) {
                Guid.ParseExact(requestId, "D");
                if (!CanRecoverFailedStart)
                    throw new IOException("SCHEMA_FAILED_START_NOT_ATTESTED");
                RequireRelease(repo, targetRelease);
                AdmitSchemaRequest(requestId); schemaFromFailedStart = true;
            }
        }
        public void AdmitStoppedSchemaMaintenance(string requestId, string targetRelease) {
            lock (stopGate) {
                Guid.ParseExact(requestId, "D");
                if (!CanStartAfterStop || !LastStop.ExactExit || LastStop.Forced || LastStop.ForcedExitConfirmed)
                    throw new IOException("SCHEMA_GRACEFUL_EXIT_REQUIRED");
                RequireRelease(repo, targetRelease);
                AdmitSchemaRequest(requestId); schemaFromFailedStart = false;
            }
        }
        public Task<StopEvidence> StopForSchemaMaintenanceAsync(string requestId, string targetRelease) {
            lock (stopGate) {
                Guid.ParseExact(requestId, "D");
                if (boundedStop != null || (LastStop != null && !CanResumeAfterSchemaStopRefusal) || terminal ||
                    !HasRetainedIdentity || !String.IsNullOrEmpty(StartupFailure))
                    throw new IOException("SCHEMA_RUNNING_OWNER_NOT_ATTESTED");
                RequireRelease(repo, targetRelease);
                AdmitSchemaRequest(requestId);
                // Deliberately use the original graceful protocol, never StopBounded.
                // Timeout/unknown is terminal for maintenance; there is no cutoff.
                schemaStopPending = true;
                return Task.Run(() => {
                    try { return Stop(requestId, targetRelease); }
                    finally { lock (stopGate) { schemaStopPending = false; } }
                });
            }
        }
        public static string SchemaSourceRelease(string repo) {
            var paths = new List<string>(Directory.GetFiles(Path.Combine(repo, "backend", "app"), "*.py", SearchOption.AllDirectories));
            paths.AddRange(Directory.GetFiles(Path.Combine(repo, "backend", "alembic"), "*.py", SearchOption.AllDirectories));
            paths.Add(Path.Combine(repo, "scripts", "omi-schema-maintenance.py"));
            paths.Add(Path.Combine(repo, "scripts", "backup-omi-sqlite.py"));
            paths.Sort((a,b) => StringComparer.Ordinal.Compare(a.Replace('\\','/'), b.Replace('\\','/')));
            using (var bytes = new MemoryStream()) using (var sha = SHA256.Create()) {
                foreach (var path in paths) {
                    RejectReparse(path);
                    var label = Encoding.UTF8.GetBytes(path.Substring(repo.TrimEnd('\\').Length + 1).Replace('\\','/') + "\0");
                    bytes.Write(label, 0, label.Length);
                    var hash = sha.ComputeHash(File.ReadAllBytes(path)); bytes.Write(hash, 0, hash.Length);
                }
                return BitConverter.ToString(sha.ComputeHash(bytes.ToArray())).Replace("-", "").ToLowerInvariant();
            }
        }
        public static string ReadStartCompatibility(string repo, string liveUrl, string database, string schemaLock, bool upgrade) {
            var entry = Path.Combine(repo, "scripts", "omi-schema-maintenance.py");
            RejectReparse(entry);
            var arguments = "-I -S -B " + Wire.Quote(entry) + " CheckStart";
            if (!String.IsNullOrEmpty(liveUrl)) arguments += " --base-url " + Wire.Quote(liveUrl);
            if (upgrade) arguments += " --upgrade";
            if (!String.IsNullOrEmpty(database) || !String.IsNullOrEmpty(schemaLock)) {
                if (!upgrade || String.IsNullOrEmpty(database) || String.IsNullOrEmpty(schemaLock))
                    throw new IOException("RESTART_COMPATIBILITY_NOT_ATTESTED");
                arguments += " --database-path " + Wire.Quote(database) + " --schema-lock-path " + Wire.Quote(schemaLock);
            }
            using (var inspector = Wire.Start(FixedPython(repo), arguments, repo, true)) {
                inspector.StandardInput.Close();
                var output = inspector.StandardOutput.ReadToEndAsync();
                var error = inspector.StandardError.ReadToEndAsync();
                // Read-only inspector: timeout refuses before STOP; never kill a
                // maintenance worker or reuse an unobserved reply as authority.
                if (!inspector.WaitForExit(20000) || !output.Wait(500) || !error.Wait(500) ||
                    inspector.ExitCode != 0 || output.Result.Length > 16384)
                    throw new IOException("RESTART_COMPATIBILITY_NOT_ATTESTED");
                return output.Result;
            }
        }
        public Task<bool> ApplyStoppedSchemaAsync(string requestId, string targetRelease, string sourceRelease,
                string database, string schemaLock, string backup, string receipt) {
            lock (stopGate) {
                if (schemaWorkerAttempted || schemaRequest != requestId || !RetainedIdentityMatches())
                    throw new IOException("SCHEMA_ADMISSION_NOT_ATTESTED");
                if (schemaFromFailedStart) {
                    if (!CanRecoverFailedStart) throw new IOException("SCHEMA_FAILED_START_NOT_ATTESTED");
                } else if (!CanStartAfterStop ||
                    !LastStop.ExactExit || LastStop.Forced || LastStop.ForcedExitConfirmed ||
                    LastStop.Reason != "LIFESPAN_AND_EXACT_EXIT") throw new IOException("SCHEMA_GRACEFUL_EXIT_REQUIRED");
                RequireRelease(repo, targetRelease);
                if (String.IsNullOrEmpty(sourceRelease) || SchemaSourceRelease(repo) != sourceRelease)
                    throw new IOException("SCHEMA_SOURCE_CHANGED");
                schemaWorkerAttempted = true; // Spawn uncertainty consumes the attempt.
                return Task.Run(() => {
                    var entry = Path.Combine(repo, "scripts", "omi-schema-maintenance.py");
                    RejectReparse(entry); RejectReparse(database); RejectReparse(schemaLock);
                    var boot = new Dictionary<string,string> { {"action", "ApplyStopped"},
                        {"request_id", requestId}, {"nonce", Wire.Nonce()},
                        {"launcher_pid", identity["launcher_pid"]}, {"launcher_created", identity["launcher_created"]},
                        {"database", database}, {"schema_lock", schemaLock}, {"backup", backup}, {"receipt", receipt} };
                    boot["source_release"] = sourceRelease;
                    using (var worker = Wire.Start(FixedPython(repo), "-I -S -B " + Wire.Quote(entry) + " ApplyStopped", repo)) {
                        // No force kill/timeout abandonment: owner admission stays fenced
                        // until this retained worker exits. Worker SQL/copy is bounded.
                        string output;
                        try {
                            Wire.Send(worker.StandardInput, boot);
                            var challenge = Wire.Decode(worker.StandardOutput.ReadLine());
                            if (!Wire.Same(boot, challenge, "request_id", "nonce") ||
                                !challenge.ContainsKey("state") || challenge["state"] != "CHALLENGE" ||
                                !challenge.ContainsKey("challenge") || challenge["challenge"].Length != 64)
                                throw new IOException("SCHEMA_WORKER_HANDSHAKE_FAILED");
                            lock (stopGate) {
                                if (schemaRequest != requestId || !RetainedIdentityMatches() ||
                                    (schemaFromFailedStart ? !CanRecoverFailedStart : !CanStartAfterStop))
                                    throw new IOException("SCHEMA_ADMISSION_LOST");
                                Wire.Send(worker.StandardInput, new Dictionary<string,string> {
                                    {"request_id", requestId}, {"nonce", boot["nonce"]},
                                    {"challenge", challenge["challenge"]}, {"action", "GO"} });
                            }
                            worker.StandardInput.Close();
                            output = worker.StandardOutput.ReadLine();
                        }
                        finally { worker.StandardInput.Close(); worker.WaitForExit(); }
                        var result = Wire.Decode(output);
                        RequireRelease(repo, targetRelease);
                        lock (stopGate) {
                            bool bound = Wire.Same(boot, result, "request_id", "nonce");
                            bool success = bound && worker.ExitCode == 0 && result["status"] == "SUCCEEDED";
                            SchemaWorkerNoChange = bound && worker.ExitCode == 2 && result["status"] == "FAILED" &&
                                result.ContainsKey("migration") && result["migration"] == "NOT_ATTEMPTED";
                            SchemaWorkerSettled = success || SchemaWorkerNoChange;
                            return success;
                        }
                    }
                });
            }
        }
        public Task<StopEvidence> StopForRestartAsync(string requestId, string targetRelease) {
            if (String.IsNullOrEmpty(targetRelease)) throw new ArgumentException("RESTART_RELEASE_REQUIRED");
            return StopWithinDeadlineAsync(requestId, targetRelease, new LifecycleDeadline());
        }
        bool RetainedIdentityMatches() {
            try {
                using (var owner = Process.GetCurrentProcess())
                    return child != null && runner != null && identity != null &&
                        owner.Id.ToString() == identity["launcher_pid"] && Wire.Created(owner) == identity["launcher_created"] &&
                        child.Id.ToString() == identity["child_pid"] && Wire.Created(child) == identity["child_created"] &&
                        runner.Id.ToString() == identity["runner_pid"] && Wire.Created(runner) == identity["runner_created"] &&
                        child.Handle != IntPtr.Zero && runner.Handle != IntPtr.Zero;
            } catch { return false; }
        }
        public Task<StopEvidence> StopWithinDeadlineAsync(string requestId, string targetRelease, LifecycleDeadline deadline) {
            Guid.ParseExact(requestId, "D");
            if (String.IsNullOrEmpty(targetRelease)) targetRelease = null;
            if (deadline == null) throw new ArgumentNullException("deadline");
            lock (stopGate) {
                if (boundedStop != null) return boundedStop;
                // The worker must never hold stopGate during IO. A blocked pipe
                // write/read or Runner wait cannot prevent the deadline callback.
                boundedStop = StopBounded(requestId, targetRelease, deadline);
                return boundedStop;
            }
        }
        async Task<StopEvidence> StopBounded(string requestId, string targetRelease, LifecycleDeadline deadline) {
            var graceful = Task.Run(() => StopOnce(requestId, targetRelease, deadline));
            var expiry = Task.Delay(deadline.RemainingMilliseconds);
            StopEvidence evidence = null;
            if (await Task.WhenAny(graceful, expiry).ConfigureAwait(false) == graceful) {
                try { evidence = await graceful.ConfigureAwait(false); } catch { }
                if (evidence != null && evidence.ExactExit && deadline.RemainingMilliseconds > 0) {
                    lock (stopGate) { LastStop = evidence; stops[requestId] = evidence; }
                    return evidence;
                }
            }
            // Rearmed/unknown is diagnostic, never a second graceful window.
            await expiry.ConfigureAwait(false);
            evidence = ForceRetainedStop(requestId, deadline, evidence);
            lock (stopGate) { terminal = true; forcedStop = evidence; LastStop = evidence; stops[requestId] = evidence; }
            // Do not await the abandoned transport task, even after termination.
            return evidence;
        }
        void SaveCutoff(StopEvidence evidence) {
            var serializer = new JavaScriptSerializer();
            File.WriteAllText(Path.Combine(identity["journal"], "hard-cutoff-" + evidence.RequestId + ".json"),
                serializer.Serialize(evidence), new UTF8Encoding(false));
        }
        StopEvidence ForceRetainedStop(string requestId, LifecycleDeadline deadline, StopEvidence graceful) {
            cutoffStarted = true; terminal = true;
            var evidence = new StopEvidence { RequestId = requestId, State = "unknown", Reason = "FORCE_OWNER_NOT_ATTESTED",
                Forced = true, AcceptedAt = deadline.AcceptedAt, CutoffAt = DateTime.UtcNow.ToString("o"),
                ElapsedMilliseconds = deadline.ElapsedMilliseconds, GracefulReason = graceful == null ? "GRACEFUL_DEADLINE" : graceful.Reason,
                PreflightStage = graceful == null ? null : graceful.PreflightStage, RecoveryState = "RECONCILIATION_REQUIRED" };
            if (!RetainedIdentityMatches()) return evidence;
            evidence.BeforePid = child.Id; evidence.BeforeCreated = ChildCreated;
            evidence.RunnerPid = runner.Id; evidence.RunnerCreated = Wire.Created(runner);
            evidence.ProcessGeneration = identity["instance"];
            try {
                // Stop the retained parent first so it cannot respawn its child.
                foreach (var process in new[] {runner, child}) {
                    try { if (!process.HasExited) process.Kill(); }
                    catch { /* Still visit the other retained target; exact exit below decides the result. */ }
                }
                var observed = Stopwatch.StartNew();
                if (!runner.WaitForExit(3000) || !child.WaitForExit(Math.Max(0, 3000 - (int)observed.ElapsedMilliseconds)))
                    evidence.Reason = "FORCED_EXIT_UNCONFIRMED";
                else {
                    evidence.ForcedExitConfirmed = true;
                    evidence.State = "forced_stopped"; evidence.Reason = "HARD_CUTOFF_EXACT_OWNED_EXIT";
                }
            } catch { evidence.State = "unknown"; evidence.ForcedExitConfirmed = false; evidence.Reason = "FORCED_EXIT_UNCONFIRMED";
            }
            // Receipt IO cannot hold termination hostage. The returned memory
            // receipt is also logged by Launcher/Controller. No DB/Job mutation.
            evidence.ReceiptPersistence = "UNCONFIRMED";
            var write = Task.Run(() => { SaveCutoff(evidence); });
            try { if (write.Wait(500)) evidence.ReceiptPersistence = "WRITTEN"; } catch { }
            return evidence;
        }
        StopEvidence StopOnce(string requestId, string targetRelease, LifecycleDeadline deadline = null) {
            var evidence = new StopEvidence { RequestId = requestId, State = "unknown", Reason = "LIFECYCLE_FAILED" };
            // Stopping the retained running image does not adopt disk source or
            // require a subsequent start/readiness check. PREPARE below is the
            // current writer authority; the READY restart snapshot is not one.
            if (terminal || !Alive) { terminal = true; evidence.Reason = "OWNER_NOT_ATTESTED"; return evidence; }
            evidence.BeforePid = ChildPid; evidence.BeforeCreated = ChildCreated;
            // A local refusal precedes all dispatch and the terminal latch.
            // Keep its UUID receipt, but do not strand the live generation.
            if (targetRelease != null) {
                try {
                    RequireRelease(repo, targetRelease);
                    if (!identity.ContainsKey("restart_abort_protocol") || identity["restart_abort_protocol"] != "1")
                        throw new IOException("RESTART_ABORT_PROTOCOL_UNAVAILABLE");
                } catch (IOException error) {
                    evidence.State = "blocked"; evidence.StopNotSent = true;
                    evidence.Reason = error.Message == "RESTART_ABORT_PROTOCOL_UNAVAILABLE" ? error.Message : "RESTART_SOURCE_CHANGED";
                    evidence.PreflightStage = "BEFORE_PREPARE";
                    return evidence;
                }
            }
            var command = Wire.Copy(identity, "REQUEST"); command["action"] = "STOP";
            var remaining = deadline == null ? 120000 : Math.Min(120000, deadline.RemainingMilliseconds);
            if (remaining <= 0) { evidence.Reason = "STOP_TIMEOUT"; return evidence; }
            command["request_id"] = requestId; command["deadline"] = (Wire.Now + remaining).ToString();
            if (targetRelease != null) command["target_release_id"] = targetRelease;
            terminal = true; // From the first possible dispatch, delivery is unknown.
            try {
                Wire.Send(runner.StandardInput, command);
                var result = Wire.Read(runner.StandardOutput, remaining);
                if (cutoffStarted) return evidence;
                if (!Wire.Same(identity, result, Wire.Identity) || !Wire.Same(command, result, "request_id", "deadline")) return evidence;
                if (result.ContainsKey("state") && result["state"] == "RESTART_NOT_SENT" &&
                    result.ContainsKey("stop_not_sent") && result["stop_not_sent"] == "true" &&
                    result.ContainsKey("stage") && result["stage"] == "BEFORE_PREPARE" &&
                    result.ContainsKey("reason") && result["reason"] == "RESTART_SOURCE_CHANGED" && Alive) {
                    evidence.State = "blocked"; evidence.Reason = "RESTART_SOURCE_CHANGED";
                    evidence.StopNotSent = true; evidence.PreflightStage = "BEFORE_PREPARE";
                    lock (stopGate) { if (!cutoffStarted) terminal = false; }
                    return evidence;
                }
                if (Wire.Rearmed(command, result) && Alive) {
                    evidence.Rearmed = true; evidence.State = "blocked"; evidence.Reason = "PREFLIGHT_REARMED";
                    evidence.PreflightStage = result.ContainsKey("stage") ? result["stage"] : null;
                    evidence.StopNotSent = result.ContainsKey("stop_not_sent") && result["stop_not_sent"] == "true";
                    lock (stopGate) { if (!cutoffStarted) terminal = false; }
                    return evidence;
                }
                if (result["state"] != "SUCCEEDED_PRODUCTION" || result["reason"] != "LIFESPAN_AND_EXACT_EXIT" ||
                    !result.ContainsKey("no_respawn") || result["no_respawn"] != "true") {
                    string reason;
                    if (result.TryGetValue("reason", out reason) && (reason == "ALL_WRITERS_DRAIN_UNAVAILABLE" ||
                        reason == "STOP_TIMEOUT" || reason == "OWNER_LOST" || reason == "ACK_MISMATCH" ||
                        reason == "LIFESPAN_NOT_COMPLETE" || reason == "EXACT_EXIT_NOT_PROVEN" ||
                        reason == "RESTART_SOURCE_CHANGED" || reason == "RESTART_REARM_NOT_ATTESTED")) evidence.Reason = reason;
                    return evidence;
                }
                if (!child.WaitForExit(1000) || child.ExitCode != 0 || !runner.WaitForExit(2000) || runner.ExitCode != 0) return evidence;
                confirmedStopReceipt = new Dictionary<string,string>(result);
                evidence.ExactExit = true; evidence.State = "stopped"; evidence.Reason = "LIFESPAN_AND_EXACT_EXIT";
            } catch (TimeoutException) { evidence.Reason = "STOP_TIMEOUT"; }
              catch (IOException error) { if (error.Message == "RESTART_SOURCE_CHANGED") evidence.Reason = error.Message; }
              catch { /* unknown delivery cannot be replayed */ }
            return evidence;
        }
        public void Dispose() {
            runner.StandardInput.Close(); runner.Dispose(); if (child != null) child.Dispose();
        }
    }

    // Constructed only in the launcher process. No HTTP/model booleans are accepted.
    // Production issue/adoption is absent until global writer fencing + independent
    // approval exist. Disposable scope is never accepted as production evidence.
    public sealed class LauncherSession : IDisposable {
        readonly Process runner;
        readonly Mutex mutex;
        readonly Dictionary<string,string> identity;
        readonly string root;
        readonly Dictionary<string,Dictionary<string,string>> receipts = new Dictionary<string,Dictionary<string,string>>();
        bool terminal;
        public Dictionary<string,string> Identity { get { return new Dictionary<string,string>(identity); } }
        public int RunnerPid { get { return runner.Id; } }
        public static LauncherSession StartDisposable(string repo, string output, string python, string scenario) {
            return new LauncherSession(repo, output, python, scenario);
        }
        LauncherSession(string repo, string output, string python, string scenario) {
            root = Path.GetFullPath(output);
            var allowed = Path.Combine(Path.GetFullPath(repo), ".tmp", "owned-shutdown") + Path.DirectorySeparatorChar;
            if (!root.StartsWith(allowed, StringComparison.OrdinalIgnoreCase) || Directory.Exists(root)) throw new IOException("FRESH_DISPOSABLE_ROOT_REQUIRED");
            Wire.PrivateDirectory(root, true);
            bool created;
            mutex = new Mutex(true, "Local\\omi-owned-fixture-" + Guid.NewGuid().ToString("N"), out created);
            if (!created) throw new IOException("MUTEX_OWNERSHIP_REQUIRED");
            var owner = Process.GetCurrentProcess();
            var boot = new Dictionary<string,string> { {"instance", Guid.NewGuid().ToString()}, {"nonce", Wire.Nonce()},
                {"launcher_pid", owner.Id.ToString()}, {"launcher_created", Wire.Created(owner)},
                {"scope", "DISPOSABLE"}, {"scenario", scenario}, {"journal", root} };
            runner = Wire.Start(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell\\v1.0\\powershell.exe"),
                "-NoProfile -File " + Wire.Quote(Path.Combine(repo, "scripts", "run-service-logged.ps1")) +
                " -OwnedShutdownChannel -ServiceName backend -RepoRoot " + Wire.Quote(repo) +
                " -WorkingDirectory " + Wire.Quote(Path.Combine(repo, "backend")) + " -FilePath " + Wire.Quote(python) +
                " -ArgumentsJsonBase64 W10= -LauncherPid " + owner.Id, repo);
            boot["runner_pid"] = runner.Id.ToString(); boot["runner_created"] = Wire.Created(runner);
            Wire.Send(runner.StandardInput, boot);
            identity = Wire.Read(runner.StandardOutput, 15000);
            if (!Wire.Same(boot, identity, "instance", "nonce", "launcher_pid", "launcher_created", "runner_pid", "runner_created") || identity["state"] != "READY")
                throw new IOException("RUNNER_HANDSHAKE_MISMATCH");
        }
        public Dictionary<string,string> StopDisposable(string requestId, string approvalRequestId, string fault) {
            lock (receipts) {
                Guid parsed;
                if (!Guid.TryParseExact(requestId, "D", out parsed)) throw new ArgumentException("UUID_REQUIRED");
                if (receipts.ContainsKey(requestId)) return new Dictionary<string,string>(receipts[requestId]);
                var result = Wire.Copy(identity, "BLOCKED"); result["request_id"] = requestId;
                // This is explicitly fixture approval, supplied independently from
                // child drain. There is no production approval issuer here.
                if (approvalRequestId != requestId) {
                    result["reason"] = "INDEPENDENT_APPROVAL_MISSING"; receipts[requestId] = result;
                    return new Dictionary<string,string>(result);
                }
                if (terminal) {
                    result["reason"] = "TERMINAL_NO_REPLAY"; receipts[requestId] = result;
                    return new Dictionary<string,string>(result);
                }
                terminal = true;
                var command = Wire.Copy(identity, "REQUEST");
                command["action"] = "STOP"; command["request_id"] = requestId;
                command["deadline"] = (Wire.Now + 1800).ToString();
                if (fault == "wrong-pid") command["child_pid"] = "1";
                if (fault == "wrong-created") command["child_created"] = "0";
                if (fault == "expired") command["deadline"] = (Wire.Now - 1).ToString();
                if (fault == "wrong-nonce") command["nonce"] = Wire.Nonce();
                if (fault == "cancel") command["action"] = "CANCEL";
                try {
                    Wire.Send(runner.StandardInput, command);
                    result = Wire.Read(runner.StandardOutput, 4500);
                    if (!Wire.Same(identity, result, Wire.Identity) || result["request_id"] != requestId) throw new IOException("RECEIPT_MISMATCH");
                } catch (Exception e) { result = Wire.Copy(command, "UNKNOWN"); result["reason"] = e.GetType().Name; }
                receipts[requestId] = result;
                return new Dictionary<string,string>(result);
            }
        }
        public bool WaitForExit(int milliseconds) { return runner.WaitForExit(milliseconds); }
        public void Disconnect() { runner.StandardInput.Close(); }
        public void Dispose() {
            runner.StandardInput.Close(); runner.Dispose(); mutex.ReleaseMutex(); mutex.Dispose();
        }
    }

    public static class Runner {
        internal static void Persist(string root, string name, Dictionary<string,string> value) {
            Wire.PrivateDirectory(root, false);
            // Fresh directory + CreateNew, write-through, fsync before delivery.
            using (var file = new FileStream(Path.Combine(root, name), FileMode.CreateNew, FileAccess.Write, FileShare.Read, 4096, FileOptions.WriteThrough)) {
                var bytes = Encoding.UTF8.GetBytes(Wire.Encode(value)); file.Write(bytes, 0, bytes.Length); file.Flush(true);
            }
        }
        public static int Run(string repo, string python, int launcherPid) {
            var boot = Wire.Decode(Console.ReadLine());
            if (boot["scope"] == "PRODUCTION") return RunProduction(repo, python, launcherPid, boot);
            var self = Process.GetCurrentProcess();
            if (boot["scope"] != "DISPOSABLE") throw new InvalidOperationException("PRODUCTION_ADMISSION_AUTHORITY_UNAVAILABLE");
            using (var owner = Process.GetProcessById(launcherPid)) {
                if (boot["launcher_pid"] != launcherPid.ToString() || boot["launcher_created"] != Wire.Created(owner) ||
                    boot["runner_pid"] != self.Id.ToString() || boot["runner_created"] != Wire.Created(self)) throw new IOException("OWNER_MISMATCH");
                var root = Path.GetFullPath(boot["journal"]);
                if (!root.StartsWith(Path.Combine(Path.GetFullPath(repo), ".tmp", "owned-shutdown") + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new IOException("DISPOSABLE_ROOT_REQUIRED");
                Wire.PrivateDirectory(root, false);
                // Fixed entry, direct base interpreter, no cmd.exe or arbitrary argv.
                using (var child = Wire.Start(python, "-I -S -B " + Wire.Quote(Path.Combine(repo, "backend", "tests", "fixtures", "owned_shutdown_child.py")), repo)) {
                    // Non-secret creation observation, also available when startup
                    // fails before READY. Never an exit/readiness attestation.
                    Persist(root, "child-observation.json", new Dictionary<string,string> {
                        {"child_pid", child.Id.ToString()}, {"child_created", Wire.Created(child)},
                        {"runner_pid", self.Id.ToString()}, {"runner_created", Wire.Created(self)} });
                    Wire.Send(child.StandardInput, boot);
                    var identity = Wire.Read(child.StandardOutput, 8000);
                    if (!Wire.Same(boot, identity, "instance", "nonce", "launcher_pid", "launcher_created", "runner_pid", "runner_created") ||
                        identity["child_pid"] != child.Id.ToString() || identity["child_created"] != Wire.Created(child) || identity["state"] != "READY") throw new IOException("CHILD_IDENTITY_MISMATCH");
                    Console.WriteLine(Wire.Encode(identity)); Console.Out.Flush();
                    var input = Task.Factory.StartNew(() => Console.ReadLine());
                    Dictionary<string,string> request = null;
                    var watch = Stopwatch.StartNew();
                    while (!input.IsCompleted && !owner.HasExited && !child.HasExited && watch.ElapsedMilliseconds < 8000) Thread.Sleep(10);
                    var result = Wire.Copy(identity, "UNKNOWN"); result["reason"] = "OWNER_OR_CHANNEL_LOST";
                    bool latched = false;
                    try {
                        if (!input.IsCompleted || input.Result == null || owner.HasExited) throw new IOException("OWNER_ABSENT");
                        request = Wire.Decode(input.Result);
                        result["request_id"] = request["request_id"];
                        Guid id; long deadline;
                        if (!Guid.TryParseExact(request["request_id"], "D", out id) || !long.TryParse(request["deadline"], out deadline) ||
                            deadline <= Wire.Now || deadline - Wire.Now > 10000 || !Wire.Same(identity, request, Wire.Identity)) throw new IOException("INTENT_IDENTITY_OR_TTL_MISMATCH");
                        var stopClock = Stopwatch.StartNew();
                        long stopBudget = deadline - Wire.Now;
                        if (request["action"] == "CANCEL") { result["state"] = "CANCELLED"; result["reason"] = "CANCELLED_BEFORE_STOP"; }
                        else {
                            if (request["action"] != "STOP") throw new IOException("FIXED_STOP_ONLY");
                            var prepare = new Dictionary<string,string>(request); prepare["action"] = "PREPARE";
                            Wire.Send(child.StandardInput, prepare);
                            var drain = Wire.Read(child.StandardOutput, Wire.Remaining(deadline, stopClock, stopBudget));
                            if (!Wire.Same(request, drain, Wire.Identity) || !Wire.Same(request, drain, "request_id", "deadline") || drain["state"] != "DISPOSABLE_DRAINED") throw new IOException("WRITER_DRAIN_NOT_ATTESTED");
                            // Terminal latch has no reset path. Any later failure, timeout,
                            // cancellation or runner crash cannot enter the legacy respawn loop.
                            latched = true;
                            Persist(root, "terminal-intent.json", request);
                            if (boot["scenario"] == "runner-crash") Environment.Exit(77);
                            if (owner.HasExited || child.HasExited || Wire.Now >= deadline) throw new IOException("OWNER_OR_DEADLINE_LOST");
                            Wire.Remaining(deadline, stopClock, stopBudget);
                            Wire.Send(child.StandardInput, request);
                            var ack = Wire.Read(child.StandardOutput, Wire.Remaining(deadline, stopClock, stopBudget));
                            if (!Wire.Same(request, ack, Wire.Identity) || !Wire.Same(request, ack, "request_id", "deadline") || ack["state"] != "STOP_ACCEPTED") throw new IOException("ACK_MISMATCH");
                            var complete = Wire.Read(child.StandardOutput, Wire.Remaining(deadline, stopClock, stopBudget));
                            if (!Wire.Same(request, complete, Wire.Identity) || !Wire.Same(request, complete, "request_id", "deadline") || complete["state"] != "LIFESPAN_COMPLETE") throw new IOException("LIFESPAN_NOT_COMPLETE");
                            if (!child.WaitForExit(Wire.Remaining(deadline, stopClock, stopBudget)) || child.ExitCode != 0 || owner.HasExited) throw new IOException("EXACT_EXIT_NOT_PROVEN");
                            Wire.Remaining(deadline, stopClock, stopBudget);
                            result["state"] = "SUCCEEDED_DISPOSABLE"; result["reason"] = "LIFESPAN_AND_EXACT_EXIT";
                            result["exact_exit"] = "true"; result["exit_code"] = child.ExitCode.ToString();
                        }
                    } catch (Exception error) { result["reason"] = error.Message; }
                    result["no_respawn"] = "true"; result["latched"] = latched.ToString().ToLowerInvariant();
                    result["child_starts"] = "1";
                    Persist(root, "result.json", result);
                    Console.WriteLine(Wire.Encode(result)); Console.Out.Flush();
                    // Keep the retained child handle through fixture cleanup. Late exit
                    // does not upgrade a timeout/unknown receipt. Never terminate a child.
                    if (!child.WaitForExit(11000)) return 79;
                    Persist(root, "exit-observation.json", new Dictionary<string,string> {
                        {"child_pid", child.Id.ToString()}, {"child_created", identity["child_created"]},
                        {"exit_code", child.ExitCode.ToString()}, {"retained_handle_signalled", "true"} });
                    return result["state"] == "SUCCEEDED_DISPOSABLE" ? 0 : 79;
                }
            }
        }

        static int RunProduction(string repo, string python, int launcherPid, Dictionary<string,string> boot) {
            bool childStartAttempted = false;
            try { return RunProductionCore(repo, python, launcherPid, boot, ref childStartAttempted); }
            catch {
                if (!childStartAttempted) {
                    var failure = Wire.Copy(boot, "START_FAILED");
                    failure["reason"] = "OWNED_START_EXIT_CONFIRMED"; failure["child_started"] = "false";
                    Console.WriteLine(Wire.Encode(failure)); Console.Out.Flush();
                }
                return 79; // No proof after an ambiguous child launch attempt.
            }
        }

        static int RunProductionCore(string repo, string python, int launcherPid, Dictionary<string,string> boot, ref bool childStartAttempted) {
            var self = Process.GetCurrentProcess();
            using (var owner = Process.GetProcessById(launcherPid)) {
                if (boot["launcher_pid"] != owner.Id.ToString() || boot["launcher_created"] != Wire.Created(owner) ||
                    boot["runner_pid"] != self.Id.ToString() || boot["runner_created"] != Wire.Created(self) ||
                    python != ProductionSession.FixedPython(repo) || boot["release_id"] != ProductionSession.ApplicationRelease(repo)) throw new IOException("PRODUCTION_BOOT_MISMATCH");
                var root = Path.GetFullPath(boot["journal"]); Wire.PrivateDirectory(root, false);
                // Journal stays under the canonical private controller store.
                string suffix;
                using (var sha = SHA256.Create()) suffix = BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(repo.ToLowerInvariant()))).Replace("-", "").ToLowerInvariant().Substring(0, 24);
                var store = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Open Market Intelligence", "runtime-control", suffix, "sessions") + Path.DirectorySeparatorChar;
                if (!root.StartsWith(store, StringComparison.OrdinalIgnoreCase)) throw new IOException("PRODUCTION_JOURNAL_MISMATCH");
                Environment.SetEnvironmentVariable("OMI_BACKEND_HOST", boot["host"]);
                Environment.SetEnvironmentVariable("OMI_BACKEND_PORT", boot["port"]);
                var entry = Path.Combine(repo, "backend", "owned_backend_entry.py"); ProductionSession.RejectReparse(entry);
                var info = new ProcessStartInfo(python, "-I -S -B " + Wire.Quote(entry)) {
                    WorkingDirectory = Path.Combine(repo, "backend"), UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
                var logDirectory = Path.Combine(repo, "logs", "backend", DateTime.Now.ToString("yyyy-MM-dd"));
                Directory.CreateDirectory(logDirectory);
                var instance = Guid.ParseExact(boot["instance"], "D");
                using (var log = new StreamWriter(new FileStream(Path.Combine(logDirectory, "backend-owned-" + self.Id + "-" + instance.ToString("N") + ".log"), FileMode.CreateNew, FileAccess.Write, FileShare.Read))) {
                childStartAttempted = true;
                using (var child = Process.Start(info)) {
                    var starting = Wire.Copy(boot, "STARTING");
                    bool readyPublished = false;
                    try {
                    var retained = child.Handle;
                    starting["child_pid"] = child.Id.ToString(); starting["child_created"] = Wire.Created(child);
                    Console.WriteLine(Wire.Encode(starting)); Console.Out.Flush();
                    var logGate = new object();
                    child.ErrorDataReceived += (sender, args) => { if (args.Data != null) lock (logGate) { log.WriteLine(args.Data); log.Flush(); } };
                    child.BeginErrorReadLine();
                    Persist(root, "child-observation.json", new Dictionary<string,string> { {"child_pid", child.Id.ToString()}, {"child_created", Wire.Created(child)} });
                    Wire.Send(child.StandardInput, boot);
                    var identity = Wire.Read(child.StandardOutput, 95000);
                    if (!Wire.Same(boot, identity, "instance", "nonce", "launcher_pid", "launcher_created", "runner_pid", "runner_created", "host", "port", "release_id") ||
                        identity["child_pid"] != child.Id.ToString() || identity["child_created"] != Wire.Created(child) || identity["state"] != "READY") throw new IOException("CHILD_READY_MISMATCH");
                    Console.WriteLine(Wire.Encode(identity)); Console.Out.Flush();
                    readyPublished = true;
                    var seen = new HashSet<string>(StringComparer.Ordinal);
                    while (true) {
                    var input = Task.Factory.StartNew(() => Console.ReadLine());
                    while (!input.IsCompleted && !owner.HasExited && !child.HasExited) Thread.Sleep(25);
                    // Loss of authority cannot grant STOP. Keep the child handle;
                    // this terminal branch never respawns or adopts a port owner.
                    if (!input.IsCompleted || input.Result == null || owner.HasExited || child.HasExited) {
                        // EOF revokes only reversible PREPARE; it does not stop
                        // the serving child. Keep its original handle until exit.
                        try { child.StandardInput.Close(); } catch { }
                        child.WaitForExit(); return 79;
                    }
                    var request = Wire.Decode(input.Result);
                    // Successor pin belongs only to Launcher -> Runner; do not
                    // leak it into the child's old-generation identity/schema.
                    string targetRelease;
                    request.TryGetValue("target_release_id", out targetRelease);
                    request.Remove("target_release_id");
                    var result = Wire.Copy(identity, "UNKNOWN"); result["reason"] = "LIFECYCLE_FAILED";
                    result["request_id"] = request["request_id"]; result["deadline"] = request["deadline"];
                    try {
                        Guid id; long deadline;
                        if (request["action"] != "STOP" || !Guid.TryParseExact(request["request_id"], "D", out id) ||
                            !Int64.TryParse(request["deadline"], out deadline) || deadline <= Wire.Now || deadline - Wire.Now > 120000 ||
                            !Wire.Same(identity, request, Wire.Identity)) throw new IOException("INTENT_MISMATCH");
                        if (!seen.Add(request["request_id"])) throw new IOException("INTENT_REPLAY");
                        if (targetRelease != null) {
                            try { ProductionSession.RequireRelease(repo, targetRelease); }
                            catch (IOException) {
                                result["state"] = "RESTART_NOT_SENT"; result["reason"] = "RESTART_SOURCE_CHANGED";
                                result["stop_not_sent"] = "true"; result["stage"] = "BEFORE_PREPARE";
                                Persist(root, "refusal-" + id.ToString("D") + ".json", result);
                                Console.WriteLine(Wire.Encode(result)); Console.Out.Flush();
                                continue;
                            }
                        }
                        var clock = Stopwatch.StartNew(); var budget = deadline - Wire.Now;
                        var prepare = Wire.Copy(request, "REQUEST"); prepare["action"] = "PREPARE";
                        Wire.Send(child.StandardInput, prepare);
                        // Prepare can drain bounded registered workers for 60s.
                        var drain = Wire.Read(child.StandardOutput, (int)Math.Min(65000, budget));
                        if (!Wire.Same(request, drain, Wire.Identity) || !Wire.Same(request, drain, "request_id", "deadline")) throw new IOException();
                        if (Wire.Rearmed(request, drain) && !owner.HasExited && !child.HasExited) {
                            result["state"] = "PREFLIGHT_REARMED"; result["reason"] = "PREFLIGHT_REARMED";
                            result["rearmed"] = "true";
                            result["stage"] = drain.ContainsKey("stage") ? drain["stage"] : "UNKNOWN";
                            Persist(root, "refusal-" + id.ToString("D") + ".json", result);
                            Console.WriteLine(Wire.Encode(result)); Console.Out.Flush();
                            continue; // New owner-approved UUID only; Controller owns deduplication.
                        }
                        if (drain["state"] != "WRITERS_PREPARED") { result["reason"] = "ALL_WRITERS_DRAIN_UNAVAILABLE"; throw new IOException(); }
                        Persist(root, "terminal-intent-" + id.ToString("D") + ".json", request);
                        if (owner.HasExited || child.HasExited) throw new IOException("OWNER_LOST");
                        Wire.Remaining(deadline, clock, budget);
                        // PREPARE may take 60s. Recheck the frozen successor image
                        // after writer drain, immediately before delivering STOP.
                        if (targetRelease != null) {
                            try { ProductionSession.RequireRelease(repo, targetRelease); }
                            catch (IOException) {
                                AbortPreparedRestart(child.StandardInput, child.StandardOutput, request, owner, child, deadline, clock, budget);
                                result["state"] = "PREFLIGHT_REARMED"; result["reason"] = "PREFLIGHT_REARMED";
                                result["rearmed"] = "true"; result["stop_not_sent"] = "true";
                                result["stage"] = "RESTART_SOURCE_CHANGED";
                                Persist(root, "refusal-" + id.ToString("D") + ".json", result);
                                Console.WriteLine(Wire.Encode(result)); Console.Out.Flush();
                                continue;
                            }
                        }
                        Wire.Send(child.StandardInput, request);
                        var ack = Wire.Read(child.StandardOutput, Wire.Remaining(deadline, clock, budget));
                        if (Wire.Rearmed(request, ack) && !owner.HasExited && !child.HasExited) {
                            result["state"] = "PREFLIGHT_REARMED"; result["reason"] = "PREFLIGHT_REARMED";
                            result["rearmed"] = "true";
                            result["stage"] = "PREPARE_AUTHORITY_EXPIRED";
                            Persist(root, "refusal-" + id.ToString("D") + ".json", result);
                            Console.WriteLine(Wire.Encode(result)); Console.Out.Flush();
                            continue;
                        }
                        if (!Wire.Same(request, ack, Wire.Identity) || !Wire.Same(request, ack, "request_id", "deadline") || ack["state"] != "STOP_ACCEPTED") throw new IOException("ACK_MISMATCH");
                        // One monotonic + wall-clock budget, covering Uvicorn's
                        // HTTP wait, Runtime's 30s drain and retained exit/receipt.
                        var complete = Wire.Read(child.StandardOutput, Wire.Remaining(deadline, clock, budget, 120000));
                        if (!Wire.Same(request, complete, Wire.Identity) || !Wire.Same(request, complete, "request_id", "deadline") || complete["state"] != "LIFESPAN_COMPLETE") throw new IOException("LIFESPAN_NOT_COMPLETE");
                        if (!child.WaitForExit(Wire.Remaining(deadline, clock, budget)) || child.ExitCode != 0 || owner.HasExited) throw new IOException("EXACT_EXIT_NOT_PROVEN");
                        Wire.Remaining(deadline, clock, budget);
                        result["state"] = "SUCCEEDED_PRODUCTION"; result["reason"] = "LIFESPAN_AND_EXACT_EXIT";
                    } catch (TimeoutException) { result["reason"] = "STOP_TIMEOUT"; }
                      catch (IOException error) {
                        if (error.Message == "OWNER_LOST" || error.Message == "ACK_MISMATCH" ||
                            error.Message == "LIFESPAN_NOT_COMPLETE" || error.Message == "EXACT_EXIT_NOT_PROVEN" ||
                            error.Message == "RESTART_SOURCE_CHANGED" || error.Message == "RESTART_REARM_NOT_ATTESTED") result["reason"] = error.Message;
                      } catch { /* fixed, non-secret failure reason retained */ }
                    result["no_respawn"] = "true";
                    Persist(root, "result.json", result);
                    Console.WriteLine(Wire.Encode(result)); Console.Out.Flush();
                    child.WaitForExit(); // Retain ownership on unknown; no force or second command.
                    return result["state"] == "SUCCEEDED_PRODUCTION" ? 0 : 79;
                    }
                    } catch {
                        // Handshake/pipe/journal failure cannot orphan an owned
                        // child or authorize respawn. Keep the original handle.
                        try { child.StandardInput.Close(); } catch { }
                        child.WaitForExit();
                        if (!readyPublished && starting.ContainsKey("child_created")) {
                            var failure = Wire.Copy(starting, "START_FAILED");
                            failure["reason"] = "OWNED_START_EXIT_CONFIRMED";
                            failure["child_exact_exit"] = "true"; failure["child_exit_code"] = child.ExitCode.ToString();
                            Persist(root, "startup-failure.json", failure);
                            Console.WriteLine(Wire.Encode(failure)); Console.Out.Flush();
                        }
                        return 79;
                    }
                }
                }
            }
        }

        internal static void AbortPreparedRestart(StreamWriter input, StreamReader output,
                Dictionary<string,string> request, Process owner, Process child,
                long deadline, Stopwatch clock, long budget) {
            if (owner.HasExited || child.HasExited) throw new IOException("OWNER_LOST");
            Wire.Remaining(deadline, clock, budget);
            var abort = Wire.Copy(request, "REQUEST"); abort["action"] = "ABORT_PREPARE";
            Wire.Send(input, abort);
            var rearm = Wire.Read(output, Wire.Remaining(deadline, clock, budget));
            if (!Wire.Rearmed(request, rearm) || !Wire.Same(abort, rearm, "action") ||
                owner.HasExited || child.HasExited) throw new IOException("RESTART_REARM_NOT_ATTESTED");
        }
    }
}
