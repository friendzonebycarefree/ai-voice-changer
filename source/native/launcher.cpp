#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <string>
#include <vector>
static std::wstring quote(const std::wstring& text) {
    std::wstring result=L"\""; size_t slashes=0;
    for(auto ch:text) {
        if(ch==L'\\') { ++slashes; continue; }
        if(ch==L'"') result.append(2*slashes+1,L'\\');
        else result.append(slashes,L'\\');
        slashes=0; result+=ch;
    }
    result.append(2*slashes,L'\\'); result+=L'"'; return result;
}
int WINAPI wWinMain(HINSTANCE,HINSTANCE,PWSTR,int) {
    std::vector<wchar_t> path(32768);
    DWORD length=GetModuleFileNameW(nullptr,path.data(),DWORD(path.size()));
    if(!length || length>=path.size()) return 1;
    std::wstring root(path.data(),length); root.resize(root.find_last_of(L"\\/"));
    root+=L"\\app";
    std::wstring python=root+L"\\_runtime\\pythonw.exe";
    std::wstring main=root+L"\\source\\main.py";
    std::wstring cmd=quote(python)+L" -I -B "+quote(main);
    int count=0; auto argv=CommandLineToArgvW(GetCommandLineW(),&count);
    if(argv) { for(int i=1;i<count;++i) cmd+=L" "+quote(argv[i]); LocalFree(argv); }
    STARTUPINFOW startup{}; startup.cb=sizeof(startup); PROCESS_INFORMATION process{};
    HANDLE job=CreateJobObjectW(nullptr,nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if(!job || !SetInformationJobObject(job,JobObjectExtendedLimitInformation,&limits,sizeof(limits))) {
        if(job) CloseHandle(job); return 1;
    }
    if(!CreateProcessW(python.c_str(),cmd.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW|CREATE_SUSPENDED,nullptr,nullptr,&startup,&process)) {
        MessageBoxW(nullptr,L"Не удалось запустить локальную среду Python. Сохраните всю папку программы вместе с _runtime и source.",L"AI Voice Changer",MB_ICONERROR);
        CloseHandle(job); return 1;
    }
    if(!AssignProcessToJobObject(job,process.hProcess)) {
        TerminateProcess(process.hProcess,1); CloseHandle(process.hThread); CloseHandle(process.hProcess); CloseHandle(job); return 1;
    }
    ResumeThread(process.hThread);
    CloseHandle(process.hThread); WaitForSingleObject(process.hProcess,INFINITE);
    DWORD code=1; GetExitCodeProcess(process.hProcess,&code); CloseHandle(process.hProcess); CloseHandle(job); return int(code);
}
