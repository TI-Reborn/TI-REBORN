using System.Drawing.Imaging;

namespace TioLauncher;

internal static class NpcGlow
{
    internal static readonly Color Amber = Color.FromArgb(255, 184, 65);

    internal static void Icon(Graphics graphics, Image image, Rectangle bounds, bool glow, float scale = 1)
    {
        if (glow)
        {
            using var shade = new ImageAttributes();
            for (int radius = 3; radius >= 1; radius--)
            {
                shade.SetColorMatrix(new ColorMatrix
                {
                    Matrix00 = 0, Matrix11 = 0, Matrix22 = 0, Matrix33 = .28f - radius * .055f,
                    Matrix40 = 1, Matrix41 = .58f, Matrix42 = .06f
                });
                for (int dy = -1; dy <= 1; dy++)
                    for (int dx = -1; dx <= 1; dx++)
                    {
                        if (dx == 0 && dy == 0) continue;
                        var edge = bounds;
                        int spread = Math.Max(1, NpcCityMenu.Pixels(radius, scale));
                        edge.Offset(dx * spread, dy * spread);
                        graphics.DrawImage(image, edge, 0, 0, image.Width, image.Height, GraphicsUnit.Pixel, shade);
                    }
            }
        }
        graphics.DrawImage(image, bounds);
    }

    internal static void Portrait(Graphics graphics, Image image, Rectangle bounds, bool glow, float scale = 1)
    {
        graphics.DrawImage(image, bounds);
        for (int distance = glow ? 3 : 1; distance >= 1; distance--)
        {
            int spread = Math.Max(1, NpcCityMenu.Pixels(distance, scale));
            var outline = Rectangle.Inflate(bounds, spread, spread);
            using var pen = new Pen(glow ? Color.FromArgb(255 - 62 * (distance - 1), Amber)
                : Color.FromArgb(86, 88, 83), Math.Max(1, scale));
            graphics.DrawRectangle(pen, outline);
        }
    }
}
