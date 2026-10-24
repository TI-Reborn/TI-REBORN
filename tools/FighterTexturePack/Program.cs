using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
string root=Path.GetFullPath(args[0]);
string folder=Path.Combine(root,"assets/fighter-model-v1");
void Blit(Graphics g,Image image,Rectangle rect)
{
 g.CompositingMode=CompositingMode.SourceCopy;g.CompositingQuality=CompositingQuality.HighQuality;
 g.InterpolationMode=InterpolationMode.HighQualityBicubic;g.PixelOffsetMode=PixelOffsetMode.HighQuality;
 using var attributes=new ImageAttributes();attributes.SetWrapMode(WrapMode.TileFlipXY);
 g.DrawImage(image,rect,0,0,image.Width,image.Height,GraphicsUnit.Pixel,attributes);
}
void SaveJpeg(Image image,string path)
{
 using var enc=new EncoderParameters(1);enc.Param[0]=new EncoderParameter(System.Drawing.Imaging.Encoder.Quality,96L);
 image.Save(path,ImageCodecInfo.GetImageEncoders().Single(c=>c.MimeType=="image/jpeg"),enc);
}
using var head=Image.FromFile(Path.Combine(folder,"generated/head-master.png"));
using var cloth=Image.FromFile(Path.Combine(folder,"generated/cloth-master-v2.png"));
using var skin=Image.FromFile(Path.Combine(root,"reports/fighter-model-20261020/source/base/models/chr_man_body.jpg"));
using(var b=new Bitmap(1024,1024))
{
 using(var g=Graphics.FromImage(b))Blit(g,head,new Rectangle(0,0,1024,1024));
 SaveJpeg(b,Path.Combine(folder,"textures/tio_vet_head.jpg"));
}
// Only atlas packing/resampling. Original/generated texels are never repainted.
using(var b=new Bitmap(2048,1024))
{
 using(var g=Graphics.FromImage(b))
 {Blit(g,cloth,new Rectangle(0,0,1024,1024));Blit(g,skin,new Rectangle(1024,0,1024,1024));}
 SaveJpeg(b,Path.Combine(folder,"textures/tio_vet_body.jpg"));
}
Console.WriteLine("Packed head1024 and shared cloth/skin2048x1024; UV islands retain normalized positions.");
