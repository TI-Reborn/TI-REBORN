using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Security.Cryptography;
using System.Text.Json;

// Deterministic asset packaging only: generated artwork is neither repainted
// nor retouched. Resample PNGs, place them in the existing fixed atlas slots,
// and build a labelled review sheet. Never modify installed game resources.
string folder=Path.GetFullPath(args[0]);
var data=JsonDocument.Parse(File.ReadAllText(Path.Combine(folder,"catalog.json")));
var items=data.RootElement.GetProperty("items").EnumerateArray().ToArray();
string FileFor(JsonElement i)=>Path.Combine(folder,$"{i.GetProperty("id").GetInt32():00}-{i.GetProperty("slug").GetString()}.png");
Bitmap Scaled(Image source,int size)
{
 var b=new Bitmap(size,size,PixelFormat.Format32bppArgb);
 using var g=Graphics.FromImage(b);g.CompositingMode=CompositingMode.SourceCopy;g.CompositingQuality=CompositingQuality.HighQuality;
 g.InterpolationMode=InterpolationMode.HighQualityBicubic;g.PixelOffsetMode=PixelOffsetMode.HighQuality;
 using var attrs=new ImageAttributes();attrs.SetWrapMode(WrapMode.TileFlipXY);
 g.DrawImage(source,new Rectangle(0,0,size,size),0,0,source.Width,source.Height,GraphicsUnit.Pixel,attrs);return b;
}
foreach(var i in items)
{
 using var image=Image.FromFile(FileFor(i));if(image.Width!=image.Height)throw new Exception("Expected square icon");
 foreach(int size in new[]{32,48,64,128,256})
 {
  string sub=Path.Combine(folder,"exports",size.ToString());Directory.CreateDirectory(sub);
  using var b=Scaled(image,size);b.Save(Path.Combine(sub,Path.GetFileName(FileFor(i))),ImageFormat.Png);
 }
}
using var sheet=new Bitmap(1440,1040,PixelFormat.Format32bppArgb);
using(var g=Graphics.FromImage(sheet))
{
 g.Clear(Color.FromArgb(22,28,31));g.SmoothingMode=SmoothingMode.AntiAlias;g.TextRenderingHint=System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
 using var title=new Font("Segoe UI",27,FontStyle.Bold);using var label=new Font("Segoe UI",13,FontStyle.Bold);using var sub=new Font("Segoe UI",10);
 using var ink=new SolidBrush(Color.FromArgb(230,218,189));using var muted=new SolidBrush(Color.FromArgb(162,172,171));
 using var card=new SolidBrush(Color.FromArgb(31,38,40));using var accent=new Pen(Color.FromArgb(126,93,49),1);
 g.DrawString("TOTAL INFLUENCE  /  НОВЫЕ ИКОНКИ СПОСОБНОСТЕЙ",title,ink,24,16);
 g.DrawString("18 способностей · по названиям и механикам · крупный вид и реальные 32 / 64 px",sub,muted,27,64);
 for(int index=0;index<items.Length;index++)
 {
  var i=items[index];int x=24+(index%6)*236,y=104+(index/6)*300;
  g.FillRectangle(card,x,y,220,284);g.DrawRectangle(accent,x,y,220,284);
  using var image=Image.FromFile(FileFor(i));using var display=Scaled(image,196);g.DrawImageUnscaled(display,x+12,y+10);
  g.DrawString(i.GetProperty("name").GetString(),label,ink,new RectangleF(x+12,y+211,200,42));
  using var small=Image.FromFile(Path.Combine(folder,"exports","32",Path.GetFileName(FileFor(i))));g.DrawImageUnscaled(small,x+12,y+244);
  using var small64=Image.FromFile(Path.Combine(folder,"exports","64",Path.GetFileName(FileFor(i))));
  // Keep the label area clear: 64px samples live on the separate size sheet.
  g.DrawString($"ID {i.GetProperty("id").GetInt32():00}   ·   32 px",sub,muted,x+54,y+252);
 }
}
sheet.Save(Path.Combine(folder,"preview.png"),ImageFormat.Png);
using var sizeSheet=new Bitmap(1080,1100,PixelFormat.Format32bppArgb);
using(var g=Graphics.FromImage(sizeSheet))
{
 g.Clear(Color.FromArgb(22,28,31));using var f=new Font("Segoe UI",12,FontStyle.Bold);using var sub=new Font("Segoe UI",10);using var ink=new SolidBrush(Color.FromArgb(230,218,189));
 g.DrawString("ЧИТАЕМОСТЬ: 32 px   /   64 px   /   128 px",f,ink,20,14);
 for(int n=0;n<items.Length;n++)
 {
  var i=items[n];int x=20+n%3*354,y=50+n/3*174;
  g.DrawString($"{i.GetProperty("id").GetInt32():00}  {i.GetProperty("name").GetString()}",sub,ink,x,y);
  int offset=0;
  foreach(int size in new[]{32,64,128})
  {
   using var image=Image.FromFile(Path.Combine(folder,"exports",size.ToString(),Path.GetFileName(FileFor(i))));
   g.DrawImageUnscaled(image,x+offset,y+22);
   offset+=size==32?48:84;
  }
 }
}
sizeSheet.Save(Path.Combine(folder,"size-preview.png"),ImageFormat.Png);
string baseline=Path.Combine(folder,"source-skills.png");
if(!File.Exists(baseline))File.Copy(@"C:\Program Files (x86)\TIOnline\base\pda\skills.png",baseline);
using var original=new Bitmap(baseline);using var atlas=(Bitmap)original.Clone();
var replaced=items.Select(i=>i.GetProperty("id").GetInt32()).ToHashSet();
foreach(var i in items)
{
 int id=i.GetProperty("id").GetInt32();using var b=new Bitmap(Path.Combine(folder,"exports","32",Path.GetFileName(FileFor(i))));
 // Copy pixels explicitly: the legacy atlas has a different DPI tag from
 // the generated images, which must never scale or shift a 32px tile.
 for(int y=0;y<32;y++)for(int x=0;x<32;x++)atlas.SetPixel(id%8*32+x,id/8*32+y,b.GetPixel(x,y));
}
int unchanged=0;
for(int y=0;y<256;y++)for(int x=0;x<256;x++)
 if(!replaced.Contains(y/32*8+x/32))
 {
  if(original.GetPixel(x,y).ToArgb()!=atlas.GetPixel(x,y).ToArgb())throw new Exception("Unrelated atlas pixel changed");unchanged++;
 }
atlas.Save(Path.Combine(folder,"skills-v1.png"),ImageFormat.Png);
var files=Directory.GetFiles(folder,"*.png",SearchOption.AllDirectories).Select(p=>new {path=Path.GetRelativePath(folder,p).Replace('\\','/'),sha256=Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(p)))}).ToArray();
File.WriteAllText(Path.Combine(folder,"package.json"),JsonSerializer.Serialize(new {schema=1,generated_icons=18,export_sizes=new[]{32,48,64,128,256},atlas_size=new[]{256,256},original_atlas_cells_preserved=64-18,unchanged_pixels=unchanged,installed=false,files},new JsonSerializerOptions{WriteIndented=true}));
Console.WriteLine(JsonSerializer.Serialize(new {passed=true,icons=18,exports=90,atlas_cells_preserved=46,unchanged_pixels=unchanged}));
