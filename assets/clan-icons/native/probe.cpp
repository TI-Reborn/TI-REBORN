#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
int wmain(int argc,wchar_t** argv) {
 if(argc!=4)return 1;
 HMODULE dll=LoadLibraryW(argv[1]);if(!dll)return 2;
 auto normalize=(const wchar_t*(__stdcall*)(const wchar_t*))GetProcAddress(dll,"NormalizeCrest");
 auto release=(void(__stdcall*)())GetProcAddress(dll,"ReleaseCrest");
 if(!normalize||!release)return 3;
 const wchar_t* path=normalize(argv[2]);if(!path)return 4;
 const int32_t* meta=(const int32_t*)path;
 if(meta[-2]!=-1||meta[-1]<=0)return 5;
 wchar_t copy[1024];wcscpy_s(copy,path);
 if(!CopyFileW(path,argv[3],FALSE))return 6;
 release();if(GetFileAttributesW(copy)!=INVALID_FILE_ATTRIBUTES)return 7;
 FreeLibrary(dll);puts("{\"native_conversion_passed\":true,\"temporary_file_removed\":true}");return 0;
}
