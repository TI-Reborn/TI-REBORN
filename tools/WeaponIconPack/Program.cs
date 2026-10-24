using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Security.Cryptography;
using System.Text.Json;

// Packaging only. All original artwork comes from built-in ImageGen.
// Preserve source files and alpha; trim empty margins, fit, resample, label sheets.
string folder=Path.GetFullPath(args[0]);
var doc=JsonDocument.Parse(File.ReadAllText(Path.Combine(folder,"catalog.json")));
var all=doc.RootElement.GetProperty("items").EnumerateArray().ToArray();
var items=all.Where(i=>File.Exists(Path.Combine(folder,i.GetProperty("file").GetString()!))).ToArray();
if(items.Length==0)throw new Exception("No generated assets");
var checks=new List<object>();
var bounds=new Dictionary<Bitmap,Rectangle>();
Bitmap Fit(Bitmap source,int width,int height,bool trim=true)
{
 var rect=new Rectangle(0,0,source.Width,source.Height);
 if(trim && bounds.TryGetValue(source,out var cached))rect=cached;
 else if(trim)
 {
  int left=source.Width,top=source.Height,right=-1,bottom=-1;
  for(int y=0;y<source.Height;y++)for(int x=0;x<source.Width;x++)
   if(source.GetPixel(x,y).A>0){left=Math.Min(left,x);top=Math.Min(top,y);right=Math.Max(right,x);bottom=Math.Max(bottom,y);}
  if(right<left)throw new Exception("Empty image");
  rect=Rectangle.FromLTRB(left,top,right+1,bottom+1);
  bounds[source]=rect;
 }
 var b=new Bitmap(width,height,PixelFormat.Format32bppArgb);
 using var g=Graphics.FromImage(b);g.CompositingMode=CompositingMode.SourceCopy;
 g.InterpolationMode=InterpolationMode.HighQualityBicubic;g.PixelOffsetMode=PixelOffsetMode.HighQuality;
 double scale=Math.Min((width-4d)/rect.Width,(height-4d)/rect.Height);
 int w=Math.Max(1,(int)Math.Round(rect.Width*scale)),h=Math.Max(1,(int)Math.Round(rect.Height*scale));
 using var attrs=new ImageAttributes();attrs.SetWrapMode(WrapMode.TileFlipXY);
 g.DrawImage(source,new Rectangle((width-w)/2,(height-h)/2,w,h),rect.X,rect.Y,rect.Width,rect.Height,GraphicsUnit.Pixel,attrs);
 return b;
}
foreach(var i in items)
{
 string name=i.GetProperty("file").GetString()!,path=Path.Combine(folder,name);
 using var image=new Bitmap(path);bool transparent=false,visible=false;
 for(int y=0;y<image.Height;y++)for(int x=0;x<image.Width;x++)
 {var a=image.GetPixel(x,y).A;transparent|=a==0;visible|=a>128;}
 if(!transparent||!visible)throw new Exception("Invalid transparency: "+name);
 foreach(var size in new[]{new Size(64,32),new Size(128,64),new Size(256,128),new Size(512,256),new Size(128,128),new Size(256,256)})
 {
  string sub=Path.Combine(folder,"exports",$"{size.Width}x{size.Height}");Directory.CreateDirectory(sub);
  using var b=Fit(image,size.Width,size.Height);b.Save(Path.Combine(sub,name),ImageFormat.Png);
 }
 checks.Add(new{id=i.GetProperty("id").GetInt32(),file=name,width=image.Width,height=image.Height,has_transparency=transparent,
  sha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant()});
}
int pages=(items.Length+14)/15;
for(int page=0;page<pages;page++)
{
 using var sheet=new Bitmap(1500,1140,PixelFormat.Format32bppArgb);
 using(var g=Graphics.FromImage(sheet))
 {
  g.Clear(Color.FromArgb(18,24,28));g.TextRenderingHint=System.Drawing.Text.TextRenderingHint.AntiAliasGridFit;
  using var title=new Font("Segoe UI",25,FontStyle.Bold);using var label=new Font("Segoe UI",14,FontStyle.Bold);using var small=new Font("Segoe UI",10);
  using var ink=new SolidBrush(Color.FromArgb(235,221,190));using var muted=new SolidBrush(Color.FromArgb(166,181,183));
  using var card=new SolidBrush(Color.FromArgb(28,37,42));using var pen=new Pen(Color.FromArgb(88,102,105));
  g.DrawString($"TOTAL INFLUENCE / WEAPONS  {page+1:00}",title,ink,24,18);
  g.DrawString("Original game names / new ImageGen artwork / transparent PNG / inventory sample 64 x 32",small,muted,26,67);
  for(int n=0;n<15;n++)
  {
   int index=page*15+n;if(index>=items.Length)break;
   var i=items[index];int x=24+n%3*490,y=108+n/3*204;
   g.FillRectangle(card,x,y,466,190);g.DrawRectangle(pen,x,y,466,190);
   using var image=new Bitmap(Path.Combine(folder,i.GetProperty("file").GetString()!));using var view=Fit(image,440,126);
   g.DrawImage(view,new Rectangle(x+13,y+6,440,126),0,0,440,126,GraphicsUnit.Pixel);
   g.DrawString(i.GetProperty("name").GetString(),label,ink,x+14,y+134);
   using var native=new Bitmap(Path.Combine(folder,"exports","64x32",i.GetProperty("file").GetString()!));
   g.DrawImage(native,new Rectangle(x+385,y+147,64,32),0,0,64,32,GraphicsUnit.Pixel);
   g.DrawString($"ID {i.GetProperty("id").GetInt32()}  /  {i.GetProperty("weapon_type").GetString()}",small,muted,x+15,y+162);
  }
 }
 sheet.Save(Path.Combine(folder,$"preview-{page+1:00}.png"),ImageFormat.Png);
}
File.WriteAllText(Path.Combine(folder,"package.json"),JsonSerializer.Serialize(new{schema=1,generated_icons=items.Length,expected_icons=all.Length,complete=items.Length==all.Length,
 installed=false,tool="built-in image_gen",export_sizes=new[]{"64x32","128x64","256x128","512x256","128x128","256x256"},files=checks},new JsonSerializerOptions{WriteIndented=true})+"\n");
Console.WriteLine($"Packaged {items.Length}/{all.Length} weapon icons, {pages} preview sheets; source artwork and alpha preserved.");
