// Compiled inside the existing OMI launcher, never a standalone lifecycle service.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace Omi.RuntimeControl {
    public static class ProcessEvidence {
        [DllImport("shell32.dll", SetLastError = true)]
        static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)] string command, out int count);
        [DllImport("kernel32.dll")]
        static extern IntPtr LocalFree(IntPtr value);
        public static string[] Arguments(string command) {
            int count;
            var pointer = CommandLineToArgvW(command, out count);
            if (pointer == IntPtr.Zero) throw new IOException("COMMAND_EVIDENCE_INVALID");
            try {
                var result = new string[count];
                for (int i = 0; i < count; i++) result[i] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(pointer, i * IntPtr.Size));
                return result;
            } finally { LocalFree(pointer); }
        }
    }
    // A report from the pinned Backend, not an all-writer/approval capability.
    public sealed class BackendPreflight {
        public string schema;
        public bool runtime_started;
        public string registered_drain_state;
        public bool all_writers_drained;
        public int unknown_writer_count;
    }
    public sealed class Identity {
        public int pid;
        public string created_at;
        public string attestation = "PROCESS_IDENTITY";
    }
    // Historical receipt decoding only; never creates execution authority.
    public sealed class LocalApproval {
        public string decision;
        public string expires_at;
        public string issuer = "launcher_local_ui";
        public string consumed_at;
    }
    public sealed class Receipt {
        public string schema = "omi.runtime-control.v1";
        public string request_id;
        public string action = "RestartBackend";
        public string actor;
        public Identity requester;
        public string confirmation;
        public string intent_consumed_at;
        public string stop_outcome;
        public string migration_outcome;
        public string successor_outcome;
        public string next_action;
        public string state;
        public string reason;
        public string owner_id;
        public Identity before;
        public Identity after;
        public string updated_at;
        public string loaded_release_identity = "UNATTESTED";
        public string application_release_id;
        public string preflight_stage;
        public string rearm_evidence;
        public Dictionary<string,object> stop_evidence;
        public string recovery_state;
        public BackendPreflight backend_preflight;
        public Identity backend_preflight_identity;
        public string[] blockers;
        public LocalApproval local_approval;
    }
    public sealed class Controller : IDisposable {
        const int Limit = 16384;
        const int Capacity = 2048;
        readonly object gate = new object();
        readonly string directory;
        readonly string tokenHash;
        readonly string pipeName;
        readonly Queue<string> pending = new Queue<string>();
        readonly ManualResetEvent listening = new ManualResetEvent(false);
        readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = Limit, RecursionLimit = 16 };
        readonly SecurityIdentifier sid = WindowsIdentity.GetCurrent().User;
        readonly HashSet<string> states = new HashSet<string> { "accepted", "running", "succeeded", "failed", "blocked", "unknown" };
        readonly HashSet<string> reasons = new HashSet<string> {
            "ACCEPTED", "RUNNING", "SUCCEEDED", "NOT_FOUND", "OWNER_MISMATCH", "OWNER_NOT_ATTESTED",
            "OWNER_APPROVAL_REQUIRED", "ALL_WRITERS_DRAIN_UNAVAILABLE", "GRACEFUL_TRANSPORT_UNAVAILABLE",
            "CONTROLLER_RECOVERED_NO_REPLAY", "LIFECYCLE_FAILED", "NEW_IDENTITY_NOT_ATTESTED",
            "READINESS_NOT_ATTESTED", "SOURCE_ADOPTION_NOT_ATTESTED", "STORE_UNAVAILABLE", "BUSY",
            "BACKEND_PREFLIGHT_NOT_ATTESTED", "WRITER_ADMISSION_NOT_ATTESTED", "SAFE_START_UNAVAILABLE",
            "OWNED_BOOTSTRAP_REQUIRED", "APPROVAL_DENIED", "NONTERMINAL_WRITER_PREFLIGHT_UNAVAILABLE", "PREFLIGHT_REARMED",
            "RESTART_SOURCE_CHANGED", "RESTART_ABORT_PROTOCOL_UNAVAILABLE", "RESTART_COMPATIBILITY_NOT_ATTESTED",
            "SCHEMA_CONFIGURED_TARGET_UNAVAILABLE"
        };
        volatile bool stopping;
        Thread thread;
        NamedPipeServerStream pipe;
        string snapshot;
        DateTime published;
        Identity backend;
        bool ownerAttested;
        string active;
        // In-memory provenance is minted only after authenticated Dispatch persists
        // accepted. Neither historical receipt loading nor public reads recreate it.
        string authenticatedIntent;
        string takenIntent;
        Process authenticatedCaller;
        Identity authenticatedCallerIdentity;
        string authenticatedAction;
        Omi.OwnedShutdown.LifecycleDeadline operationDeadline;
        public string OwnerId { get; private set; }

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetNamedPipeClientProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe, out uint pid);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetNamedPipeServerProcessId(Microsoft.Win32.SafeHandles.SafePipeHandle pipe, out uint pid);

        // Read-only observation for the one-shot updater. It cannot queue work.
        public static string ReadOwnerStatus(string name, Process owner) {
            return RequestOwner(name, owner, "{\"action\":\"Status\",\"request_id\":\"\",\"expected_owner_id\":\"\",\"token\":\"\"}");
        }
        // Bounded client used by the existing local adapter, with retained server
        // PID/creation handle. No HTTP, process discovery, shell or fallback.
        public static string RequestOwner(string name, Process owner, string message) {
            if (Encoding.UTF8.GetByteCount(message) >= Limit || message.IndexOf('\n') >= 0)
                throw new ArgumentException("INVALID_REQUEST");
            if (owner.Handle == IntPtr.Zero || owner.HasExited) throw new IOException("OWNER_NOT_ATTESTED");
            using (var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous)) {
                client.Connect(500);
                uint pid;
                if (owner.HasExited || !GetNamedPipeServerProcessId(client.SafePipeHandle, out pid) || pid != owner.Id)
                    throw new IOException("UPDATE_SUCCESSOR_OWNER_MISMATCH");
                var payload = Encoding.UTF8.GetBytes(message + "\n");
                var write = client.BeginWrite(payload, 0, payload.Length, null, null);
                using (var wait = write.AsyncWaitHandle) {
                    if (!wait.WaitOne(500)) throw new IOException("UPDATE_STATUS_TIMEOUT");
                    client.EndWrite(write);
                }
                var buffer = new byte[Limit]; int length = 0;
                var watch = Stopwatch.StartNew();
                while (length < Limit && watch.ElapsedMilliseconds < 1500) {
                    var read = client.BeginRead(buffer, length, Limit - length, null, null);
                    using (var wait = read.AsyncWaitHandle) {
                        if (!wait.WaitOne(Math.Max(0, 1500 - (int)watch.ElapsedMilliseconds))) break;
                        var count = client.EndRead(read);
                        if (count == 0) break;
                        length += count;
                    }
                    if (buffer[length - 1] == 10 && !owner.HasExited) return Encoding.UTF8.GetString(buffer, 0, length);
                }
                throw new IOException("UPDATE_STATUS_UNCONFIRMED");
            }
        }

        public static string[] UnavailableRestartGates() {
            // Implementation gaps, not mutable flags or reported capabilities.
            return new[] { "WRITER_ADMISSION_NOT_ATTESTED", "ALL_WRITERS_DRAIN_UNAVAILABLE",
                "GRACEFUL_TRANSPORT_UNAVAILABLE", "SAFE_START_UNAVAILABLE",
                "READINESS_NOT_ATTESTED", "SOURCE_ADOPTION_NOT_ATTESTED" };
        }
        Process PipeClient(NamedPipeServerStream server) {
            Process process = null;
            try {
                uint pid, retainedPid;
                if (!GetNamedPipeClientProcessId(server.SafePipeHandle, out pid)) return null;
                process = Process.GetProcessById(checked((int)pid));
                if (process.Handle == IntPtr.Zero || process.HasExited ||
                    !GetNamedPipeClientProcessId(server.SafePipeHandle, out retainedPid) || pid != retainedPid)
                    throw new IOException("PIPE_CLIENT_NOT_ATTESTED");
                return process;
            } catch { if (process != null) process.Dispose(); return null; }
        }
        Identity ClientIdentity(Process process) {
            try {
                if (process == null || process.Handle == IntPtr.Zero || process.HasExited) return null;
                return new Identity { pid = process.Id, created_at = process.StartTime.ToUniversalTime().ToString("o") };
            } catch { return null; }
        }
        void ReleaseCaller() {
            if (authenticatedCaller != null) authenticatedCaller.Dispose();
            authenticatedCaller = null; authenticatedCallerIdentity = null; authenticatedAction = null;
        }
        static string Confirmation(string action) {
            switch (action) {
                case "RestartBackend": return "restart_backend";
                case "StartBackend": return "start_backend";
                case "RecoverFailedStart": return "recover_failed_start";
                case "SchemaUpgrade": return "upgrade_schema";
                default: return null;
            }
        }
        bool SameIdentity(Identity left, Identity right) {
            return ValidIdentity(left) && ValidIdentity(right) && left.pid == right.pid
                && left.created_at == right.created_at;
        }
        bool ValidPreflight(BackendPreflight report) {
            return report != null && report.schema == "omi.restart-preflight.v1"
                && (report.registered_drain_state == "NOT_REQUESTED" || report.registered_drain_state == "REGISTERED_DRAINED"
                    || report.registered_drain_state == "INCOMPLETE" || report.registered_drain_state == "IN_PROGRESS"
                    || report.registered_drain_state == "UNKNOWN")
                && report.unknown_writer_count >= 0 && report.unknown_writer_count <= 1024;
        }
        BackendPreflight ParsePreflight(string value) {
            if (value == null || value.Length > 1024) return null;
            try {
                var fields = json.Deserialize<Dictionary<string, object>>(value);
                if (fields == null || fields.Count != 5 || !fields.ContainsKey("schema")
                    || !fields.ContainsKey("registered_drain_state") || !fields.ContainsKey("runtime_started")
                    || !fields.ContainsKey("all_writers_drained") || !fields.ContainsKey("unknown_writer_count")
                    || !(fields["runtime_started"] is bool) || !(fields["all_writers_drained"] is bool)
                    || !(fields["unknown_writer_count"] is int)) return null;
                var report = json.Deserialize<BackendPreflight>(value);
                return ValidPreflight(report) ? report : null;
            } catch { return null; }
        }

        public Controller(string storeDirectory, string configuredTokenHash, string name) {
            directory = Path.GetFullPath(storeDirectory);
            pipeName = name;
            tokenHash = ValidTokenHash(configuredTokenHash) ? configuredTokenHash : null;
            OwnerId = Guid.NewGuid().ToString("D");
            PrepareStore();
            Recover();
        }

        void PrepareStore() {
            // Do not follow reparse points or repair an existing untrusted ACL.
            for (var node = new DirectoryInfo(directory); node != null; node = node.Parent)
                if (node.Exists && (node.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("STORE_UNAVAILABLE");
            if (!Directory.Exists(directory)) {
                var security = new DirectorySecurity();
                security.SetOwner(sid);
                security.SetAccessRuleProtection(true, false);
                security.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
                    InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
                Directory.CreateDirectory(directory, security);
            }
            ValidateAcl(directory, true);
        }
        void ValidateAcl(string path, bool isDirectory) {
            if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) throw new IOException("STORE_UNAVAILABLE");
            FileSystemSecurity acl = isDirectory ? (FileSystemSecurity)Directory.GetAccessControl(path) : File.GetAccessControl(path);
            if (!sid.Equals(acl.GetOwner(typeof(SecurityIdentifier)))) throw new IOException("STORE_UNAVAILABLE");
            bool own = false;
            foreach (FileSystemAccessRule rule in acl.GetAccessRules(true, true, typeof(SecurityIdentifier))) {
                if (rule.AccessControlType != AccessControlType.Allow) continue;
                if (!sid.Equals(rule.IdentityReference)) throw new IOException("STORE_UNAVAILABLE");
                if ((rule.FileSystemRights & FileSystemRights.FullControl) == FileSystemRights.FullControl) own = true;
            }
            if (!own) throw new IOException("STORE_UNAVAILABLE");
        }
        string Id(string id) { return Guid.ParseExact(id, "D").ToString("D"); }
        string ReceiptPath(string id) { return Path.Combine(directory, Id(id) + ".json"); }
        Receipt Unknown(string id, string reason) {
            return new Receipt { request_id = Id(id), state = "unknown", reason = reason, owner_id = OwnerId };
        }
        void Save(Receipt receipt) {
            ValidateAcl(directory, true);
            string target = ReceiptPath(receipt.request_id);
            string temp = Path.Combine(directory, Guid.NewGuid().ToString("N") + ".tmp");
            receipt.updated_at = DateTime.UtcNow.ToString("o");
            var bytes = Encoding.UTF8.GetBytes(json.Serialize(receipt));
            // Elevated Windows runner tokens otherwise give new files the
            // Administrators owner, which our exact-SID readback rejects.
            // Bind the private ACL at creation, before any receipt bytes exist.
            var security = new FileSecurity();
            security.SetOwner(sid);
            security.SetAccessRuleProtection(true, false);
            security.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, AccessControlType.Allow));
            try {
                using (var stream = new FileStream(temp, FileMode.CreateNew, FileSystemRights.Write, FileShare.None, 4096, FileOptions.WriteThrough, security)) {
                    stream.Write(bytes, 0, bytes.Length);
                    stream.Flush(true);
                }
                if (File.Exists(target)) { ValidateAcl(target, false); File.Replace(temp, target, null); }
                else File.Move(temp, target);
            } finally { if (File.Exists(temp)) File.Delete(temp); }
        }
        bool ValidIdentity(Identity identity) {
            DateTime parsed;
            return identity != null && identity.pid > 0 && identity.attestation == "PROCESS_IDENTITY"
                && identity.created_at != null && identity.created_at.Length <= 40
                && DateTime.TryParse(identity.created_at, out parsed);
        }
        static bool OfflineAction(string action) {
            return action == "StartBackend" || action == "RecoverFailedStart" || action == "SchemaUpgrade";
        }
        Receipt Read(string id) {
            string path = ReceiptPath(id);
            if (!File.Exists(path)) return Unknown(id, "NOT_FOUND");
            ValidateAcl(directory, true); ValidateAcl(path, false);
            if (new FileInfo(path).Length > Limit) throw new IOException("STORE_UNAVAILABLE");
            var value = json.Deserialize<Receipt>(File.ReadAllText(path, Encoding.UTF8));
            Guid owner;
            DateTime updated;
            if (value == null || value.schema != "omi.runtime-control.v1" || value.request_id != Id(id)
                || (value.action != "RestartBackend" && !OfflineAction(value.action)) || !states.Contains(value.state) || !reasons.Contains(value.reason)
                || (OfflineAction(value.action) && ((value.actor != "authenticated_pipe_client" && value.actor != "launcher_local_operator") || !ValidIdentity(value.requester)))
                || !Guid.TryParseExact(value.owner_id, "D", out owner) || !DateTime.TryParse(value.updated_at, out updated)
                || (value.loaded_release_identity != "UNATTESTED" && value.loaded_release_identity != "APPLICATION_SOURCE_SNAPSHOT")
                || (value.loaded_release_identity == "APPLICATION_SOURCE_SNAPSHOT" && !ValidTokenHash(value.application_release_id))
                || (value.before != null && !ValidIdentity(value.before)) || (value.after != null && !ValidIdentity(value.after))
                || (value.backend_preflight != null && (!ValidPreflight(value.backend_preflight)
                    || !SameIdentity(value.backend_preflight_identity, value.before)))
                || (value.backend_preflight == null && value.backend_preflight_identity != null))
                throw new IOException("STORE_UNAVAILABLE");
            if (value.blockers != null) {
                if (value.blockers.Length > 10) throw new IOException("STORE_UNAVAILABLE");
                foreach (var blocker in value.blockers) if (!reasons.Contains(blocker)) throw new IOException("STORE_UNAVAILABLE");
            }
            if (value.local_approval != null) {
                DateTime expires;
                if (value.local_approval.issuer != "launcher_local_ui"
                    || (value.local_approval.decision != "approved" && value.local_approval.decision != "denied")
                    || !DateTime.TryParse(value.local_approval.expires_at, out expires)) throw new IOException("STORE_UNAVAILABLE");
                DateTime consumed;
                if (value.local_approval.consumed_at != null && !DateTime.TryParse(value.local_approval.consumed_at, out consumed)) throw new IOException("STORE_UNAVAILABLE");
            }
            return value;
        }
        void Recover() {
            int count = 0;
            foreach (string path in Directory.EnumerateFiles(directory, "*.json")) {
                if (++count > Capacity) throw new IOException("STORE_UNAVAILABLE");
                var receipt = Read(Path.GetFileNameWithoutExtension(path));
                if (receipt.state == "accepted" || receipt.state == "running") {
                    receipt.state = "unknown"; receipt.reason = "CONTROLLER_RECOVERED_NO_REPLAY"; Save(receipt);
                }
            }
        }
        static bool ValidTokenHash(string value) {
            if (value == null || value.Length != 64) return false;
            foreach (char c in value) if (!(c >= '0' && c <= '9') && !(c >= 'a' && c <= 'f')) return false;
            return true;
        }
        bool Authorized(string token) {
            if (tokenHash == null || tokenHash.Length != 64 || token == null || token.Length != 64) return false;
            foreach (char c in token) if (!(c >= '0' && c <= '9') && !(c >= 'a' && c <= 'f')) return false;
            string actual;
            using (var sha = SHA256.Create()) actual = BitConverter.ToString(sha.ComputeHash(Encoding.ASCII.GetBytes(token))).Replace("-", "").ToLowerInvariant();
            int difference = 0;
            for (int i = 0; i < 64; i++) difference |= actual[i] ^ tokenHash[i];
            return difference == 0;
        }
        public void Publish(string statusJson, Identity ownedBackend, bool attested) {
            lock (gate) {
                if (statusJson.Length > Limit) throw new ArgumentException("RESPONSE_TOO_LARGE");
                var status = json.Deserialize<Dictionary<string, object>>(statusJson);
                var restart = status.ContainsKey("restart") ? status["restart"] as Dictionary<string, object> : null;
                // Writer/source/readiness observations are not admission authority.
                // The authenticated exact owned Backend may request bounded stop.
                // A locally started successor must retire accepted intent for
                // the previous Backend before it can receive a fresh request.
                // Running receipts belong to CompleteOwnedRestart instead.
                if (active != null) {
                    var receipt = Read(active);
                    if (receipt.action == "RestartBackend" && receipt.state == "accepted" && (!attested || !SameIdentity(receipt.before, ownedBackend))) {
                        receipt.state = "blocked"; receipt.reason = !attested || !SameIdentity(receipt.before, ownedBackend)
                            ? "OWNER_NOT_ATTESTED" : "ALL_WRITERS_DRAIN_UNAVAILABLE";
                        receipt.blockers = new[] { receipt.reason };
                        Save(receipt); active = null;
                    }
                }
                status["schema"] = "omi.runtime-control.v1"; status["owner_id"] = OwnerId;
                snapshot = json.Serialize(status);
                published = DateTime.UtcNow;
                backend = ownedBackend; ownerAttested = attested && ValidIdentity(ownedBackend);
            }
        }
        public string Dispatch(string message) { return Dispatch(message, null); }
        string Dispatch(string message, Process caller) {
            lock (gate) {
                try {
                    var fields = json.Deserialize<Dictionary<string, object>>(message);
                    if (fields == null) throw new ArgumentException();
                    foreach (var field in fields) if (field.Value != null && !(field.Value is string)) throw new ArgumentException();
                    var request = json.Deserialize<Dictionary<string, string>>(message);
                    var pipeClient = ClientIdentity(caller);
                    if (request == null || (request.Count != 4 && !(request.Count == 5 && (request.ContainsKey("backend_preflight") || request.ContainsKey("confirmation"))))
                        || !request.ContainsKey("action") || !request.ContainsKey("request_id")
                        || !request.ContainsKey("expected_owner_id") || !request.ContainsKey("token")) throw new ArgumentException();
                    if (request.ContainsKey("backend_preflight") && request["action"] != "RestartBackend") throw new ArgumentException();
                    bool offline = OfflineAction(request["action"]);
                    if (request.ContainsKey("confirmation") && request["confirmation"] != Confirmation(request["action"])) throw new ArgumentException();
                    if (offline && !request.ContainsKey("confirmation")) throw new ArgumentException();
                    if (request["action"] == "Status") return snapshot != null && (DateTime.UtcNow - published).TotalSeconds < 15
                        ? snapshot : "{\"schema\":\"omi.runtime-control.v1\",\"owner_id\":null,\"reason\":\"OWNER_NOT_ATTESTED\"}";
                    string id = Id(request["request_id"]);
                    if (request["action"] == "ReadOperation") return json.Serialize(Read(id));
                    if (request["action"] != "RestartBackend" && !offline) throw new ArgumentException();
                    if (!Authorized(request["token"])) return "{\"schema\":\"omi.runtime-control.v1\",\"error\":\"RUNTIME_CONTROL_FORBIDDEN\"}";
                    // Exact replay returns the durable original, including after owner replacement.
                    var existing = Read(id);
                    if (existing.reason != "NOT_FOUND") {
                        if (existing.action != request["action"]) return json.Serialize(Unknown(id, "CONTROLLER_RECOVERED_NO_REPLAY"));
                        if (request["expected_owner_id"] != existing.owner_id) return json.Serialize(Unknown(id, "OWNER_MISMATCH"));
                        return json.Serialize(existing);
                    }
                    if (request["expected_owner_id"] != OwnerId) return json.Serialize(Unknown(id, "OWNER_MISMATCH"));
                    if (!ValidIdentity(pipeClient)) return json.Serialize(new Receipt { request_id = id, action = request["action"],
                        owner_id = OwnerId, state = "blocked", reason = ownerAttested ? "BACKEND_PREFLIGHT_NOT_ATTESTED" : "OWNER_NOT_ATTESTED" });
                    var acceptedDeadline = new Omi.OwnedShutdown.LifecycleDeadline();
                    int count = 0;
                    foreach (var ignored in Directory.EnumerateFiles(directory, "*.json")) if (++count >= Capacity) throw new IOException();
                    var receipt = new Receipt { request_id = id, owner_id = OwnerId, before = backend,
                        action = request["action"], actor = "authenticated_pipe_client",
                        requester = pipeClient, confirmation = Confirmation(request["action"]),
                        state = "accepted", reason = "ACCEPTED" };
                    // Bind observations to the OS pipe caller and the launcher's
                    // already-owned Backend. HTTP/model input cannot supply identity.
                    if (SameIdentity(pipeClient, backend) && request.ContainsKey("backend_preflight")) {
                        receipt.backend_preflight = ParsePreflight(request["backend_preflight"]);
                        if (receipt.backend_preflight != null) receipt.backend_preflight_identity = pipeClient;
                    }
                    if ((!offline && !ownerAttested) || snapshot == null || (DateTime.UtcNow - published).TotalSeconds >= 15) { receipt.state = "blocked"; receipt.reason = "OWNER_NOT_ATTESTED"; }
                    else if (active != null) { receipt.state = "blocked"; receipt.reason = "BUSY"; }
                    else if ((backend != null && pipeClient.pid == backend.pid && !SameIdentity(pipeClient, backend)) ||
                        (request.ContainsKey("backend_preflight") && !SameIdentity(pipeClient, backend))) {
                        receipt.state = "blocked"; receipt.reason = "BACKEND_PREFLIGHT_NOT_ATTESTED";
                    }
                    if (receipt.state == "blocked") {
                        var blockers = new List<string> { receipt.reason };
                        if (receipt.backend_preflight == null) blockers.Add("BACKEND_PREFLIGHT_NOT_ATTESTED");
                        blockers.AddRange(UnavailableRestartGates());
                        receipt.blockers = blockers.ToArray();
                    }
                    if (receipt.state == "accepted") {
                        ReleaseCaller();
                        authenticatedCaller = Process.GetProcessById(pipeClient.pid);
                        if (!SameIdentity(pipeClient, ClientIdentity(authenticatedCaller))) { ReleaseCaller(); throw new IOException(); }
                        authenticatedCallerIdentity = pipeClient; authenticatedAction = receipt.action;
                    }
                    Save(receipt); // Receipt is durable BEFORE queueing any owner action.
                    if (receipt.state == "accepted") {
                        active = id; authenticatedIntent = id; takenIntent = null;
                        operationDeadline = acceptedDeadline;
                        pending.Enqueue(id);
                    }
                    return json.Serialize(receipt);
                } catch { return "{\"schema\":\"omi.runtime-control.v1\",\"state\":\"unknown\",\"reason\":\"STORE_UNAVAILABLE\"}"; }
            }
        }
        public string TakePending() {
            lock (gate) {
                while (pending.Count != 0) {
                    var id = pending.Peek();
                    var receipt = Read(id);
                    if (receipt.state == "accepted" && receipt.owner_id == OwnerId && active == id) {
                        if (FreshAuthenticatedIntent(id) && (OfflineAction(receipt.action) || (ownerAttested && SameIdentity(receipt.before, backend)))) {
                            pending.Dequeue(); takenIntent = id; return id;
                        }
                        receipt.state = "blocked"; receipt.reason = "OWNER_NOT_ATTESTED";
                        receipt.blockers = new[] { receipt.reason };
                        Save(receipt); active = null;
                    }
                    pending.Dequeue();
                }
                return null;
            }
        }
        public string PendingAction(string id) {
            lock (gate) {
                var receipt = Read(Id(id));
                if (active != id || takenIntent != id || receipt.state != "accepted") throw new InvalidOperationException();
                return receipt.action;
            }
        }
        public bool BeginRemoteOperation(string id) {
            lock (gate) {
                var receipt = Read(Id(id));
                if (!OfflineAction(receipt.action) || active != id || takenIntent != id ||
                    receipt.state != "accepted" || receipt.owner_id != OwnerId) return false;
                bool authenticated = FreshAuthenticatedIntent(id);
                authenticatedIntent = null; takenIntent = null; ReleaseCaller();
                receipt.state = authenticated ? "running" : "blocked";
                receipt.reason = authenticated ? "RUNNING" : "OWNER_NOT_ATTESTED";
                if (authenticated) receipt.intent_consumed_at = DateTime.UtcNow.ToString("o");
                else active = null;
                try { Save(receipt); } // One durable consume before any owner lifecycle action.
                catch { active = null; throw; }
                return authenticated;
            }
        }
        public void CompleteRemoteOperation(string id, bool verified, string stop, string migration,
                string successor, Identity after, string failure) {
            lock (gate) {
                var receipt = Read(Id(id));
                if (!OfflineAction(receipt.action) || active != id || receipt.state != "running" || receipt.owner_id != OwnerId)
                    throw new InvalidOperationException();
                // Success requires the owner's freshly published exact new generation.
                verified = verified && successor == "VERIFIED" && ownerAttested && SameIdentity(after, backend)
                    && (receipt.before == null || !SameIdentity(receipt.before, after))
                    && (DateTime.UtcNow - published).TotalSeconds < 15;
                receipt.state = verified ? "succeeded" : "unknown";
                receipt.reason = verified ? "SUCCEEDED" : "LIFECYCLE_FAILED";
                receipt.stop_outcome = stop; receipt.migration_outcome = migration;
                receipt.successor_outcome = successor; receipt.after = after;
                receipt.next_action = verified ? "Status" : "ReadOperation_then_reconcile_retained_generation";
                // Fixed diagnostics only; never persist arbitrary exception text or paths.
                if (failure == "SCHEMA_CONFIGURED_TARGET_UNAVAILABLE") {
                    receipt.reason = failure; receipt.state = "blocked";
                    receipt.next_action = "Status_then_CheckStart_configured_target_diagnostics";
                }
                Save(receipt); active = null;
            }
        }
        public void BlockOwnedRestart(string id, string reason) {
            lock (gate) {
                var receipt = Read(id);
                if (receipt.state != "accepted" || receipt.owner_id != OwnerId || active != id) return;
                if (!reasons.Contains(reason)) throw new ArgumentException("FIXED_REASON_REQUIRED");
                receipt.state = "blocked"; receipt.reason = reason; receipt.blockers = new[] { reason };
                Save(receipt); active = null;
            }
        }
        bool FreshAuthenticatedIntent(string id) {
            // An accepted operation does not expire into a writer refusal. If
            // dispatch was delayed, the same elapsed deadline cuts off at once.
            var receipt = Read(id);
            return authenticatedIntent == id && operationDeadline != null &&
                authenticatedAction == receipt.action && receipt.confirmation == Confirmation(receipt.action) &&
                receipt.actor == "authenticated_pipe_client" && receipt.local_approval == null && receipt.intent_consumed_at == null &&
                SameIdentity(receipt.requester, authenticatedCallerIdentity) &&
                SameIdentity(authenticatedCallerIdentity, ClientIdentity(authenticatedCaller));
        }
        public bool BeginAuthenticatedOwnedRestart(string id, Identity current) {
            id = Id(id);
            lock (gate) {
                var receipt = Read(id);
                if (receipt.state != "accepted" || receipt.owner_id != OwnerId || active != id) return false;
                // TakePending must hand off this exact singleton. A direct caller
                // cannot consume a queued intent before the Launcher tick takes it.
                if (takenIntent != id) return false;
                bool exact = false;
                try { using (var process = Process.GetProcessById(current.pid)) exact = !process.HasExited && process.StartTime.ToUniversalTime().ToString("o") == current.created_at; }
                catch { }
                string reason = null;
                if (!FreshAuthenticatedIntent(id) || !exact || !ownerAttested ||
                    !SameIdentity(current, backend) || !SameIdentity(current, receipt.before)) reason = "OWNER_NOT_ATTESTED";
                else if (receipt.local_approval != null || (receipt.blockers != null && receipt.blockers.Length != 0))
                    reason = "CONTROLLER_RECOVERED_NO_REPLAY";
                // Consume in-memory authority BEFORE saving. An ambiguous store
                // failure can never be retried into STOP, even in this process.
                authenticatedIntent = null; takenIntent = null; ReleaseCaller();
                receipt.intent_consumed_at = DateTime.UtcNow.ToString("o");
                receipt.state = reason == null ? "running" : "blocked";
                receipt.reason = reason ?? "RUNNING";
                receipt.blockers = reason == null ? new string[0] : new[] { reason };
                Save(receipt); // durable running BEFORE existing PREPARE/STOP
                if (reason != null) active = null;
                return reason == null;
            }
        }
        public Omi.OwnedShutdown.LifecycleDeadline OwnedRestartDeadline(string id) {
            lock (gate) {
                if (active != id || operationDeadline == null) throw new InvalidOperationException("NO_ACCEPTED_DEADLINE");
                return operationDeadline;
            }
        }
        public void CompleteOwnedRestart(string id, Omi.OwnedShutdown.ProductionSession.StopEvidence stopped,
                                         Omi.OwnedShutdown.ProductionSession next, Identity verifiedIdentity,
                                         string beforeStopReason = null, bool successorAttempted = false) {
            lock (gate) {
                var receipt = Read(id);
                if (receipt.state != "running" || receipt.owner_id != OwnerId || active != id) throw new InvalidOperationException();
                receipt.state = "unknown"; receipt.reason = "LIFECYCLE_FAILED";
                receipt.stop_outcome = stopped == null ? "UNKNOWN" : stopped.State;
                receipt.migration_outcome = "NOT_ATTEMPTED";
                receipt.successor_outcome = next == null ? (successorAttempted ? "ATTEMPTED_UNCONFIRMED" : "NOT_ATTEMPTED") : "FAILED_UNCONFIRMED";
                receipt.next_action = "ReadOperation_then_reconcile_retained_generation";
                receipt.stop_evidence = stopped == null ? null : json.Deserialize<Dictionary<string,object>>(json.Serialize(stopped));
                receipt.recovery_state = stopped != null && stopped.Forced ? "RECONCILIATION_REQUIRED" : null;
                if (stopped != null && stopped.RequestId == id && stopped.BeforePid == receipt.before.pid &&
                    stopped.BeforeCreated == receipt.before.created_at && !stopped.Rearmed &&
                    ((stopped.ExactExit && stopped.State == "stopped" && stopped.Reason == "LIFESPAN_AND_EXACT_EXIT") ||
                     (stopped.ForcedExitConfirmed && stopped.State == "forced_stopped" && stopped.Reason == "HARD_CUTOFF_EXACT_OWNED_EXIT"))) {
                    if (next != null && next.Alive && next.ChildPid != receipt.before.pid && next.ChildCreated != receipt.before.created_at) {
                        receipt.after = new Identity { pid = next.ChildPid, created_at = next.ChildCreated };
                        receipt.reason = "READINESS_NOT_ATTESTED";
                        // Verification occurred before this lock; HTTP readiness
                        // queries this controller and must never run under gate.
                        if (next.StartReadinessVerified && SameIdentity(receipt.after, verifiedIdentity) &&
                            ownerAttested && SameIdentity(backend, receipt.after) &&
                            (DateTime.UtcNow - published).TotalSeconds < 15) {
                            receipt.loaded_release_identity = "APPLICATION_SOURCE_SNAPSHOT";
                            receipt.application_release_id = next.ReleaseId;
                            receipt.state = "succeeded"; receipt.reason = "SUCCEEDED";
                            receipt.successor_outcome = "VERIFIED"; receipt.next_action = "Status";
                        }
                    } else { receipt.state = "failed"; receipt.reason = "SAFE_START_UNAVAILABLE"; }
                } else if (stopped != null && stopped.RequestId == id && stopped.BeforePid == receipt.before.pid &&
                           stopped.BeforeCreated == receipt.before.created_at && stopped.Rearmed) {
                    receipt.state = "blocked"; receipt.reason = "PREFLIGHT_REARMED";
                    receipt.preflight_stage = stopped.PreflightStage;
                    receipt.rearm_evidence = "INHERITED_OWNER_ACK_SAME_LIVE_PROCESS";
                } else if (!ApplyBeforePrepareRefusal(receipt, stopped) && stopped != null &&
                           stopped.Reason == "ALL_WRITERS_DRAIN_UNAVAILABLE") receipt.reason = stopped.Reason;
                if (stopped == null && (beforeStopReason == "RESTART_SOURCE_CHANGED" ||
                    beforeStopReason == "RESTART_COMPATIBILITY_NOT_ATTESTED" ||
                    beforeStopReason == "SOURCE_ADOPTION_NOT_ATTESTED" || beforeStopReason == "OWNER_NOT_ATTESTED")) {
                    receipt.state = "blocked"; receipt.reason = beforeStopReason;
                    receipt.stop_outcome = "NOT_ATTEMPTED"; receipt.preflight_stage = "BEFORE_STOP";
                    receipt.next_action = beforeStopReason == "SOURCE_ADOPTION_NOT_ATTESTED"
                        ? "Explicit_Launcher_update_required"
                        : beforeStopReason == "OWNER_NOT_ATTESTED" ? "Status_then_reconcile_retained_owner"
                        : "CheckStart_then_explicit_SchemaUpgrade_or_approved_release";
                }
                receipt.blockers = receipt.state == "succeeded" ? new string[0] : new[] { receipt.reason };
                Save(receipt); active = null;
            }
        }
        internal static bool ApplyBeforePrepareRefusal(Receipt receipt, Omi.OwnedShutdown.ProductionSession.StopEvidence stopped) {
            if (receipt.before == null || stopped == null || stopped.RequestId != receipt.request_id ||
                stopped.BeforePid != receipt.before.pid || stopped.BeforeCreated != receipt.before.created_at ||
                !stopped.StopNotSent || stopped.ExactExit || stopped.Rearmed || stopped.State != "blocked" ||
                stopped.PreflightStage != "BEFORE_PREPARE" ||
                (stopped.Reason != "RESTART_SOURCE_CHANGED" && stopped.Reason != "RESTART_ABORT_PROTOCOL_UNAVAILABLE")) return false;
            receipt.state = "blocked"; receipt.reason = stopped.Reason;
            receipt.preflight_stage = stopped.PreflightStage;
            return true;
        }
        public void Start() {
            if (thread != null) throw new InvalidOperationException();
            thread = new Thread(Serve) { IsBackground = true, Name = "OMI fixed runtime pipe" };
            thread.Start();
            if (!listening.WaitOne(1500)) { Dispose(); throw new IOException("PIPE_UNAVAILABLE"); }
        }
        void Serve() {
            while (!stopping) {
                try {
                    var security = new PipeSecurity();
                    security.SetOwner(sid); security.SetAccessRuleProtection(true, false);
                    security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.NetworkSid, null), PipeAccessRights.FullControl, AccessControlType.Deny));
                    security.AddAccessRule(new PipeAccessRule(sid, PipeAccessRights.FullControl, AccessControlType.Allow));
                    using (var server = new NamedPipeServerStream(pipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
                        PipeOptions.Asynchronous, Limit, Limit, security)) {
                        pipe = server;
                        listening.Set();
                        server.WaitForConnection();
                        using (var caller = PipeClient(server)) {
                            var bytes = new List<byte>();
                            var watch = Stopwatch.StartNew();
                            while (bytes.Count < Limit && watch.ElapsedMilliseconds < 1500) {
                                var chunk = new byte[1024];
                                var read = server.BeginRead(chunk, 0, chunk.Length, null, null);
                                int count;
                                using (var wait = read.AsyncWaitHandle) {
                                    if (!wait.WaitOne(Math.Max(1, 1500 - (int)watch.ElapsedMilliseconds))) break;
                                    count = server.EndRead(read);
                                }
                                if (count == 0) break;
                                for (int i = 0; i < count; i++) bytes.Add(chunk[i]);
                                if (bytes.Count > Limit) break;
                                if (bytes[bytes.Count - 1] == 10) {
                                    var reply = Encoding.UTF8.GetBytes(Dispatch(Encoding.UTF8.GetString(bytes.ToArray()), caller) + "\n");
                                    var write = server.BeginWrite(reply, 0, reply.Length, null, null);
                                    using (var wait = write.AsyncWaitHandle) if (wait.WaitOne(500)) server.EndWrite(write);
                                    break;
                                }
                            }
                        }
                    }
                } catch { if (!stopping) Thread.Sleep(100); }
            }
        }
        public void Dispose() { stopping = true; var current = pipe; if (current != null) current.Dispose(); if (thread != null) thread.Join(2500); lock (gate) { ReleaseCaller(); } }
    }
}
