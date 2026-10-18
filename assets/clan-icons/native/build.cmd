@echo off
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars32.bat" >nul
if errorlevel 1 exit /b 1
cl /nologo /LD /MT /O2 /W4 /WX /EHsc /DUNICODE /D_UNICODE assets\clan-icons\native\crest_image.cpp /Fowork\clan-icons-20261018\crest_image.obj /link /DEF:assets\clan-icons\native\crest_image.def /OUT:reports\clan-icons-20261018\tio_crest.dll /IMPLIB:work\clan-icons-20261018\crest_image.lib user32.lib
if errorlevel 1 exit /b 1
cl /nologo /MT /O2 /W4 /WX /EHsc /DUNICODE /D_UNICODE assets\clan-icons\native\probe.cpp /Fowork\clan-icons-20261018\probe.obj /Fework\clan-icons-20261018\crest_probe.exe
