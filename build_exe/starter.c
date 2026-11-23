/* MudPilot.exe at the top of the install: opens the newest compiled version in app\<version>\ (the launcher there
   does the rest), passing on any arguments ('--data PVE'). No Python in here, so an update never needs to
   replace it while something has it open. A version named in data\control\skip-versions.txt is passed over
   (one that crashed on install). */
#include <windows.h>
#include <wchar.h>
#include <stdio.h>
#include <string.h>

static int parse(const wchar_t *s, int v[8]) {
    int n = 0;
    while (*s && n < 8) {
        if (*s < L'0' || *s > L'9') return 0;
        v[n] = 0;
        while (*s >= L'0' && *s <= L'9') v[n] = v[n] * 10 + (*s++ - L'0');
        n++;
        if (*s == L'.') s++; else if (*s) return 0;
    }
    return *s ? 0 : n;
}

static int newer(const int a[8], int na, const int b[8], int nb) {
    for (int i = 0; i < 8; i++) {
        int x = i < na ? a[i] : 0, y = i < nb ? b[i] : 0;
        if (x != y) return x > y;
    }
    return 0;
}

static int skipped(const wchar_t *root, const wchar_t *ver) {
    wchar_t p[MAX_PATH * 2];
    swprintf(p, MAX_PATH * 2, L"%ls\\data\\control\\skip-versions.txt", root);
    FILE *f = _wfopen(p, L"r");
    if (!f) return 0;
    char line[64], want[64];
    WideCharToMultiByte(CP_UTF8, 0, ver, -1, want, sizeof want, NULL, NULL);
    int hit = 0;
    while (fgets(line, sizeof line, f)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!strcmp(line, want)) { hit = 1; break; }
    }
    fclose(f);
    return hit;
}

int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR cmd, int show) {
    wchar_t root[MAX_PATH], pat[MAX_PATH * 2], best[64] = L"", exe[MAX_PATH * 2];
    GetModuleFileNameW(NULL, root, MAX_PATH);
    *wcsrchr(root, L'\\') = 0;
    swprintf(pat, MAX_PATH * 2, L"%ls\\app\\*", root);
    int bv[8] = {0}, bn = 0;
    WIN32_FIND_DATAW fd;
    HANDLE fh = FindFirstFileW(pat, &fd);
    if (fh != INVALID_HANDLE_VALUE) {
        do {
            int v[8], n;
            if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || !(n = parse(fd.cFileName, v))) continue;
            swprintf(exe, MAX_PATH * 2, L"%ls\\app\\%ls\\MudPilot.exe", root, fd.cFileName);
            if (GetFileAttributesW(exe) == INVALID_FILE_ATTRIBUTES || skipped(root, fd.cFileName)) continue;
            if (!bn || newer(v, n, bv, bn)) { memcpy(bv, v, sizeof bv); bn = n; wcsncpy(best, fd.cFileName, 63); }
        } while (FindNextFileW(fh, &fd));
        FindClose(fh);
    }
    if (!bn) {
        MessageBoxW(NULL, L"MudPilot isn't installed properly: there's no app folder next to MudPilot.exe.\n"
                    L"Unzip the whole MudPilot download again.", L"MudPilot", MB_ICONERROR);
        return 1;
    }
    swprintf(exe, MAX_PATH * 2, L"%ls\\app\\%ls\\MudPilot.exe", root, best);
    size_t len = wcslen(exe) + wcslen(cmd) + 32;
    wchar_t *line = (wchar_t *)HeapAlloc(GetProcessHeap(), 0, len * sizeof(wchar_t));
    swprintf(line, len, L"\"%ls\" -m mudpilot.launcher %ls", exe, cmd);
    STARTUPINFOW si = {sizeof si};
    PROCESS_INFORMATION pi;
    if (!CreateProcessW(exe, line, NULL, NULL, FALSE, 0, NULL, root, &si, &pi)) {
        MessageBoxW(NULL, L"Couldn't start MudPilot.", L"MudPilot", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
