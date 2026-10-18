// Local image preparation only. The original client sends the resulting BMP.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objidl.h>
#include <gdiplus.h>
#include <stdint.h>
#include <string.h>
#include <wchar.h>
#pragma comment(lib,"gdiplus.lib")
using namespace Gdiplus;
struct DelphiPath { uint16_t codepage, element; int32_t refs, length; wchar_t text[1024]; };
static DelphiPath output;
static void error() { MessageBoxW(nullptr,L"Choose a valid PNG or BMP image (up to 4096 x 4096 pixels and 16 MB).\nThe image will be fitted to a 16 x 16 clan icon.",L"Clan icon / Значок клана",MB_OK|MB_ICONWARNING); }
extern "C" __declspec(dllexport) void __stdcall ReleaseCrest() {
 if(output.text[0]) DeleteFileW(output.text);
 ZeroMemory(&output,sizeof(output));
}
extern "C" __declspec(dllexport) const wchar_t* __stdcall NormalizeCrest(const wchar_t* path) {
 ReleaseCrest();
 if(!path||!path[0]||wcslen(path)>=32760) {error();return nullptr;}
 HANDLE source=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
 if(source==INVALID_HANDLE_VALUE){error();return nullptr;}
 LARGE_INTEGER size; BYTE magic[8]={};DWORD count=0;
 bool valid=GetFileSizeEx(source,&size)&&size.QuadPart>0&&size.QuadPart<=16*1024*1024&&ReadFile(source,magic,8,&count,nullptr)&&count>=2;
 CloseHandle(source);
 bool png=count==8&&!memcmp(magic,"\x89PNG\r\n\x1a\n",8),bmp=magic[0]=='B'&&magic[1]=='M';
 if(!valid||(!png&&!bmp)){error();return nullptr;}
 ULONG_PTR token=0;GdiplusStartupInput init;
 if(GdiplusStartup(&token,&init,nullptr)!=Ok){error();return nullptr;}
 BYTE pixels[768]={};bool good=false;
 {
  Bitmap original(path,FALSE);
  UINT width=original.GetWidth(),height=original.GetHeight();
  if(original.GetLastStatus()==Ok&&width>0&&height>0&&width<=4096&&height<=4096) {
   Bitmap target(16,16,PixelFormat24bppRGB);
   Graphics g(&target);g.Clear(Color(255,0,0,0));
   g.SetCompositingMode(CompositingModeSourceOver);
   g.SetInterpolationMode(InterpolationModeHighQualityBicubic);
   g.SetPixelOffsetMode(PixelOffsetModeHalf);
   double scale=min(16.0/width,16.0/height);int w=max(1,(int)(width*scale+0.5)),h=max(1,(int)(height*scale+0.5));
   good=g.DrawImage(&original,Rect((16-w)/2,(16-h)/2,w,h),0,0,width,height,UnitPixel)==Ok;
   g.Flush(FlushIntentionSync);
   for(UINT y=0;y<16&&good;y++)for(UINT x=0;x<16;x++) {
    Color c;if(target.GetPixel(x,y,&c)!=Ok){good=false;break;}
    unsigned off=(15-y)*48+x*3;pixels[off]=c.GetB();pixels[off+1]=c.GetG();pixels[off+2]=c.GetR();
   }
  }
 }
 GdiplusShutdown(token);
 if(!good){error();return nullptr;}
 wchar_t temp[900];DWORD n=GetTempPathW(900,temp);
 if(!n||n>=900){error();return nullptr;}
 if(swprintf_s(output.text,L"%stio-crest-%lu.bmp",temp,GetCurrentProcessId())<0){error();return nullptr;}
 BYTE canonical[822]={};BITMAPFILEHEADER fh={};BITMAPINFOHEADER ih={};
 fh.bfType=0x4d42;fh.bfSize=822;fh.bfOffBits=54;
 ih.biSize=40;ih.biWidth=16;ih.biHeight=16;ih.biPlanes=1;ih.biBitCount=24;ih.biSizeImage=768;
 memcpy(canonical,&fh,14);memcpy(canonical+14,&ih,40);memcpy(canonical+54,pixels,768);
 HANDLE file=CreateFileW(output.text,GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_TEMPORARY,nullptr);
 DWORD written=0;good=file!=INVALID_HANDLE_VALUE&&WriteFile(file,canonical,822,&written,nullptr)&&written==822;
 if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);
 if(!good){ReleaseCrest();error();return nullptr;}
 output.codepage=1200;output.element=2;output.refs=-1;output.length=(int32_t)wcslen(output.text);
 return output.text;
}
