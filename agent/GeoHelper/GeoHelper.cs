// Helper WinRT: Geolocator → JSON no stdout.
using System.Text;
using System.Text.Json;
using Windows.Devices.Geolocation;
using Windows.Foundation;

internal sealed class Program
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    [STAThread]
    private static int Main()
    {
        Console.OutputEncoding = Encoding.UTF8;
        try
        {
            using var mre = new ManualResetEventSlim(false);
            Geoposition? position = null;
            Exception? err = null;

            // High = prioriza GNSS/precisão. GetGeopositionAsync() sem args pode devolver
            // cache antigo (ex.: bairro de dias atrás) — maximumAge Zero exige fix novo.
            var locator = new Geolocator { DesiredAccuracy = PositionAccuracy.High };
            var maxAge = TimeSpan.Zero;
            var wait = TimeSpan.FromSeconds(25);
            var op = locator.GetGeopositionAsync(maxAge, wait);
            op.Completed = (info, status) =>
            {
                try
                {
                    switch (status)
                    {
                        case AsyncStatus.Completed:
                            position = info.GetResults();
                            break;
                        case AsyncStatus.Error:
                            err = info.ErrorCode;
                            break;
                        case AsyncStatus.Canceled:
                            err = new OperationCanceledException("Operação cancelada");
                            break;
                    }
                }
                finally
                {
                    mre.Set();
                }
            };

            if (!mre.Wait(TimeSpan.FromSeconds(30)))
            {
                WriteError("Timeout de 30 segundos ao obter posição");
                return 1;
            }

            if (err != null)
            {
                WriteError(err.Message);
                return 1;
            }

            if (position == null)
            {
                WriteError("Posição não disponível");
                return 1;
            }

            var coord = position.Coordinate;
            double lat = coord.Point.Position.Latitude;
            double lon = coord.Point.Position.Longitude;
            double acc = coord.Accuracy;

            if (double.IsNaN(lat) || double.IsNaN(lon) || double.IsNaN(acc))
            {
                WriteError("Coordenadas ou precisão inválidas (NaN)");
                return 1;
            }

            var ok = new { lat, lon, accuracy = acc };
            Console.WriteLine(JsonSerializer.Serialize(ok, JsonOpts));
            return 0;
        }
        catch (Exception ex)
        {
            WriteError(ex.Message);
            return 1;
        }
    }

    private static void WriteError(string message)
    {
        var err = new { error = message };
        Console.WriteLine(JsonSerializer.Serialize(err, JsonOpts));
    }
}
