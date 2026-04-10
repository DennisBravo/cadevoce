using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Text.Json;

namespace CadeVoce.Installer;

internal static class Program
{
    private const string InstallRootFolder = "CadeVoceAgent";
    private const string PayloadResourceSuffix = "payload.zip";
    private const string SettingsResourceSuffix = "InstallSettings.json";

    private sealed class InstallSettings
    {
        public string ApiUrl { get; set; } = "";
        public string ApiKey { get; set; } = "";
        public int IntervalMinutes { get; set; } = 10;
        public string EstadoPermitido { get; set; } = "SP";
    }

    [STAThread]
    private static int Main()
    {
        var logPath = Path.Combine(Path.GetTempPath(), "cadevoce-install.log");
        try
        {
            // Single-file: GetExecutingAssembly() pode ser o host sem recursos; usar o assembly do tipo.
            var asm = typeof(Program).Assembly;
            using var settingsStream = OpenEmbedded(asm, SettingsResourceSuffix)
                ?? throw new InvalidOperationException("Recurso InstallSettings.json nao encontrado no executavel.");
            var jsonOpts = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
            var settings = JsonSerializer.Deserialize<InstallSettings>(settingsStream, jsonOpts)
                ?? throw new InvalidOperationException("InstallSettings.json invalido.");
            if (string.IsNullOrWhiteSpace(settings.ApiUrl) || string.IsNullOrWhiteSpace(settings.ApiKey))
                throw new InvalidOperationException("apiUrl e apiKey sao obrigatorios em InstallSettings.json.");
            if (settings.IntervalMinutes is < 1 or > 1439)
                throw new InvalidOperationException("intervalMinutes deve estar entre 1 e 1439.");
            var estado = string.IsNullOrWhiteSpace(settings.EstadoPermitido)
                ? "SP"
                : settings.EstadoPermitido.Trim();

            using var zipStream = OpenEmbedded(asm, PayloadResourceSuffix)
                ?? throw new InvalidOperationException("Recurso payload.zip nao encontrado no executavel.");

            var root = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                InstallRootFolder);
            Directory.CreateDirectory(root);
            var rootNorm = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

            using (var zip = new ZipArchive(zipStream, ZipArchiveMode.Read))
            {
                foreach (var entry in zip.Entries)
                {
                    if (string.IsNullOrEmpty(entry.Name) && entry.FullName.EndsWith('/'))
                        continue;
                    var destPath = Path.GetFullPath(Path.Combine(root, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                    var destNorm = destPath.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                    var underRoot = destNorm.Equals(rootNorm, StringComparison.OrdinalIgnoreCase)
                        || destNorm.StartsWith(rootNorm + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                        || destNorm.StartsWith(rootNorm + Path.AltDirectorySeparatorChar, StringComparison.OrdinalIgnoreCase);
                    if (!underRoot)
                        throw new InvalidOperationException("Entrada ZIP invalida (path traversal).");
                    var dir = Path.GetDirectoryName(destPath);
                    if (!string.IsNullOrEmpty(dir))
                        Directory.CreateDirectory(dir);
                    entry.ExtractToFile(destPath, overwrite: true);
                }
            }

            var installPs1 = Path.Combine(root, "install-task.ps1");
            if (!File.Exists(installPs1))
                throw new InvalidOperationException("install-task.ps1 nao extraido.");

            using var proc = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.Windows),
                        "System32",
                        "WindowsPowerShell",
                        "v1.0",
                        "powershell.exe"),
                    WorkingDirectory = root,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden,
                },
            };
            proc.StartInfo.ArgumentList.Add("-NoProfile");
            proc.StartInfo.ArgumentList.Add("-NonInteractive");
            proc.StartInfo.ArgumentList.Add("-WindowStyle");
            proc.StartInfo.ArgumentList.Add("Hidden");
            proc.StartInfo.ArgumentList.Add("-ExecutionPolicy");
            proc.StartInfo.ArgumentList.Add("Bypass");
            proc.StartInfo.ArgumentList.Add("-File");
            proc.StartInfo.ArgumentList.Add(installPs1);
            proc.StartInfo.ArgumentList.Add("-ApiUrl");
            proc.StartInfo.ArgumentList.Add(settings.ApiUrl.TrimEnd('/'));
            proc.StartInfo.ArgumentList.Add("-ApiKey");
            proc.StartInfo.ArgumentList.Add(settings.ApiKey);
            proc.StartInfo.ArgumentList.Add("-IntervalMinutes");
            proc.StartInfo.ArgumentList.Add(settings.IntervalMinutes.ToString());
            proc.StartInfo.ArgumentList.Add("-EstadoPermitido");
            proc.StartInfo.ArgumentList.Add(estado);

            if (!File.Exists(proc.StartInfo.FileName))
            {
                proc.StartInfo.FileName = "powershell.exe";
            }

            proc.StartInfo.RedirectStandardOutput = true;
            proc.StartInfo.RedirectStandardError = true;
            proc.Start();
            var stdoutTask = proc.StandardOutput.ReadToEndAsync();
            var stderrTask = proc.StandardError.ReadToEndAsync();
            proc.WaitForExit();
            var stdout = stdoutTask.GetAwaiter().GetResult();
            var stderr = stderrTask.GetAwaiter().GetResult();
            if (proc.ExitCode != 0)
            {
                try
                {
                    File.AppendAllText(
                        logPath,
                        $"{DateTime.UtcNow:o} install-task.ps1 exit={proc.ExitCode}{Environment.NewLine}--- STDOUT ---{Environment.NewLine}{stdout}{Environment.NewLine}--- STDERR ---{Environment.NewLine}{stderr}{Environment.NewLine}");
                }
                catch
                {
                    // ignore
                }
            }

            return proc.ExitCode == 0 ? 0 : proc.ExitCode;
        }
        catch (Exception ex)
        {
            try
            {
                File.AppendAllText(logPath, $"{DateTime.UtcNow:o} {ex}{Environment.NewLine}");
            }
            catch
            {
                // ignore
            }

            return 1;
        }
    }

    private static Stream? OpenEmbedded(Assembly asm, string nameEndsWith)
    {
        foreach (var res in asm.GetManifestResourceNames())
        {
            if (res.EndsWith(nameEndsWith, StringComparison.OrdinalIgnoreCase))
                return asm.GetManifestResourceStream(res);
        }

        return null;
    }
}
