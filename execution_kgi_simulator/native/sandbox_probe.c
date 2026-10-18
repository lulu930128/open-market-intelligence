/* Fixed no-secret child. Never accepts hosts, commands, credentials or SDK paths.
 * Only launcher-owned synthetic files and documentation-only IP addresses.
 * Build with the reviewed local compiler; inspect/pin PE imports before launch.
 */
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0602
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdio.h>

static int network_probe(int family, int udp, const char *address, int port) {
    SOCKET s = socket(family, udp ? SOCK_DGRAM : SOCK_STREAM, 0);
    int result, code = 0, size;
    u_long nonblocking = 1;
    struct sockaddr_storage storage;
    fd_set writes, errors;
    struct timeval timeout = {0, 250000};
    if (s == INVALID_SOCKET) return WSAGetLastError();
    ZeroMemory(&storage, sizeof(storage));
    if (family == AF_INET) {
        struct sockaddr_in *a = (struct sockaddr_in *)&storage;
        a->sin_family = AF_INET; a->sin_port = htons((u_short)port);
        if (InetPtonA(AF_INET, address, &a->sin_addr) != 1) { closesocket(s); return -2; }
        size = sizeof(*a);
    } else {
        struct sockaddr_in6 *a = (struct sockaddr_in6 *)&storage;
        a->sin6_family = AF_INET6; a->sin6_port = htons((u_short)port);
        if (InetPtonA(AF_INET6, address, &a->sin6_addr) != 1) { closesocket(s); return -2; }
        size = sizeof(*a);
    }
    if (ioctlsocket(s, FIONBIO, &nonblocking)) { code = WSAGetLastError(); closesocket(s); return code; }
    result = udp ? sendto(s, "X", 1, 0, (struct sockaddr *)&storage, size)
                 : connect(s, (struct sockaddr *)&storage, size);
    if (result == SOCKET_ERROR) {
        code = WSAGetLastError();
        if (!udp && code == WSAEWOULDBLOCK) {
            FD_ZERO(&writes); FD_ZERO(&errors); FD_SET(s, &writes); FD_SET(s, &errors);
            result = select(0, NULL, &writes, &errors, &timeout);
            if (result > 0) {
                int length = sizeof(code);
                if (getsockopt(s, SOL_SOCKET, SO_ERROR, (char *)&code, &length)) code = WSAGetLastError();
            } else code = result == 0 ? WSAETIMEDOUT : WSAGetLastError();
        }
    }
    closesocket(s);
    return code;
}

static DWORD file_probe(const wchar_t *base, const wchar_t *relative, DWORD access, DWORD creation, DWORD flags) {
    wchar_t path[1024];
    HANDLE h;
    DWORD error;
    if (wcslen(base) + wcslen(relative) + 2 >= 1024) return ERROR_INVALID_NAME;
    wcscpy(path, base); wcscat(path, L"\\"); wcscat(path, relative);
    h = CreateFileW(path, access, FILE_SHARE_READ, NULL, creation, flags, NULL);
    if (h == INVALID_HANDLE_VALUE) return GetLastError();
    error = 0;
    if (creation == CREATE_NEW) {
        DWORD written = 0;
        if (!WriteFile(h, "SYNTHETIC", 9, &written, NULL) || written != 9) error = GetLastError();
    }
    CloseHandle(h);
    return error;
}

int wmain(int argc, wchar_t **argv) {
    WSADATA data;
    int n[12], i, ok = 1, startup;
    DWORD f[8];
    if (argc != 2) return 97;
    startup = WSAStartup(MAKEWORD(2, 2), &data);
    if (startup) { printf("{\"startup_error\":%d}\n", startup); return 4; }
    n[0] = network_probe(AF_INET, 0, "192.0.2.1", 9);
    n[1] = network_probe(AF_INET6, 0, "2001:db8::1", 9);
    n[2] = network_probe(AF_INET, 1, "192.0.2.1", 9);
    n[3] = network_probe(AF_INET6, 1, "2001:db8::1", 9);
    n[4] = network_probe(AF_INET, 0, "127.0.0.1", 9);
    n[5] = network_probe(AF_INET6, 0, "::1", 9);
    n[6] = network_probe(AF_INET, 1, "127.0.0.1", 9);
    n[7] = network_probe(AF_INET6, 1, "::1", 9);
    n[8] = network_probe(AF_INET6, 0, "::ffff:127.0.0.1", 9);
    /* Explicit synthetic proxy transport; no system/user proxy discovery. */
    n[9] = network_probe(AF_INET, 0, "127.0.0.1", 8080);
    n[10] = network_probe(AF_INET6, 0, "::1", 8080);
    /* Non-DNS single-byte marker on documentation-only address, port 53. */
    n[11] = network_probe(AF_INET, 1, "192.0.2.1", 53);
    WSACleanup();
    f[0] = file_probe(argv[1], L"outside\\sentinel.txt", GENERIC_READ, OPEN_EXISTING, 0);
    f[1] = file_probe(argv[1], L"outside\\sentinel.txt", GENERIC_WRITE, OPEN_EXISTING, 0);
    f[2] = file_probe(argv[1], L"scratch\\sdk\\cwd-sentinel.txt", GENERIC_WRITE, OPEN_EXISTING, 0);
    f[3] = file_probe(argv[1], L"scratch\\ca", FILE_LIST_DIRECTORY, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS);
    f[4] = file_probe(argv[1], L"scratch\\logs\\control.txt", GENERIC_WRITE, CREATE_NEW, 0);
    f[5] = file_probe(argv[1], L"scratch\\sdk\\cwd-sentinel.txt", GENERIC_READ, OPEN_EXISTING, 0);
    /* Native SDK chdir analogue: a write from SDK cwd must still be denied. */
    {
        wchar_t cwd[1024];
        if (wcslen(argv[1]) + 20 >= 1024) return 98;
        wcscpy(cwd, argv[1]); wcscat(cwd, L"\\scratch\\sdk");
        f[7] = SetCurrentDirectoryW(cwd) ? 0 : GetLastError();
        f[6] = f[7] == 0 ? file_probe(L".", L"native-log.txt", GENERIC_WRITE, CREATE_NEW, 0) : ERROR_INVALID_FUNCTION;
    }
    printf("{\"schema\":\"omi.kgi-synthetic-child.v1\",\"pid\":%lu,\"network_errors\":[", GetCurrentProcessId());
    for (i = 0; i < 12; ++i) { printf("%s%d", i ? "," : "", n[i]); if (n[i] != WSAEACCES) ok = 0; }
    printf("],\"file_errors\":[");
    for (i = 0; i < 8; ++i) { printf("%s%lu", i ? "," : "", f[i]); if (f[i] != (i == 4 || i == 5 || i == 7 ? 0 : ERROR_ACCESS_DENIED)) ok = 0; }
    printf("]}\n");
    return ok ? 0 : 3;
}
