using System.Text.Json;

namespace TioLauncher;

// Native adapters depend on specific Silver bytes: their own patch sites, the
// code/data their injected code calls or reads and the F7 extension block.
// Whole-file hashes disabled every adapter after unrelated client releases;
// compare only those reviewed regions (tools/build_launcher_silver_regions.py).
static class SilverRegions
{
    internal sealed record Region(uint Rva,string Hex);
    internal sealed record Document(int Schema,string BaseSha256,Dictionary<string,Region[]> Adapters);
    internal static readonly Document Plan=Load();
    static Document Load()
    {
        using var stream=typeof(SilverRegions).Assembly.GetManifestResourceStream("TioLauncher.native-silver-regions.json")!;
        var plan=JsonSerializer.Deserialize<Document>(stream,new JsonSerializerOptions{PropertyNameCaseInsensitive=true,
            PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower})!;
        if(plan.Schema!=1 || plan.Adapters.Count==0 || plan.Adapters.Values.Any(r=>r.Length==0))
            throw new InvalidDataException("Invalid native Silver region plan.");
        return plan;
    }

    // File offset of an RVA inside a section's raw data, or -1 when absent.
    internal static long Offset(byte[] image,uint rva,int size)
    {
        if(image.Length<0x40 || image[0]!='M' || image[1]!='Z') return -1;
        int pe=BitConverter.ToInt32(image,0x3c);
        if(pe<0 || pe+24>image.Length || BitConverter.ToUInt32(image,pe)!=0x4550) return -1;
        int sections=BitConverter.ToUInt16(image,pe+6),headers=pe+24+BitConverter.ToUInt16(image,pe+20);
        for(int i=0;i<sections;i++)
        {
            int at=headers+i*40;
            if(at+40>image.Length) return -1;
            uint start=BitConverter.ToUInt32(image,at+12),raw=BitConverter.ToUInt32(image,at+16),pointer=BitConverter.ToUInt32(image,at+20);
            if(rva>=start && (ulong)rva+(ulong)size<=(ulong)start+raw)
            {
                long offset=(long)pointer+(rva-start);
                return offset+size<=image.Length?offset:-1;
            }
        }
        return -1;
    }

    internal static bool Matches(byte[] image,string adapter)
    {
        if(!Plan.Adapters.TryGetValue(adapter,out var regions)) return false;
        foreach(var region in regions)
        {
            byte[] expected=Convert.FromHexString(region.Hex);
            long offset=Offset(image,region.Rva,expected.Length);
            if(offset<0 || !image.AsSpan(checked((int)offset),expected.Length).SequenceEqual(expected)) return false;
        }
        return true;
    }

    // Accept the reviewed base and an unrelated later release; reject a change
    // inside any region of every adapter, and an unknown adapter name.
    internal static void Test(string image,string output)
    {
        byte[] raw=File.ReadAllBytes(image);
        var lines=new List<string>();
        foreach(var (name,regions) in Plan.Adapters)
        {
            if(!Matches(raw,name)) throw new InvalidDataException("Reviewed image rejected for "+name);
            foreach(var region in regions)
            {
                byte[] changed=(byte[])raw.Clone();
                long offset=Offset(changed,region.Rva,region.Hex.Length/2);
                changed[offset+region.Hex.Length/4]^=0x5a;
                if(Matches(changed,name)) throw new InvalidDataException("Changed dependency accepted for "+name);
            }
            lines.Add(name+": "+regions.Length+" regions");
        }
        byte[] unrelated=(byte[])raw.Clone();
        long outside=Offset(unrelated,0x1000,1);
        unrelated[outside]^=0x5a;
        if(Plan.Adapters.Keys.Any(name=>!Matches(unrelated,name))) throw new InvalidDataException("Unrelated byte rejected an adapter");
        if(Matches(raw,"unknown")) throw new InvalidDataException("Unknown adapter accepted");
        File.WriteAllText(output,"PASS: "+string.Join("; ",lines)+"; unrelated change accepted; changed dependencies and unknown adapter rejected");
    }
}
