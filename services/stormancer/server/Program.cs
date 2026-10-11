using RsmmBackend;
using Stormancer.Server.Hosting;

public class Program
{
    public static async Task Main(string[] args)
    {
        // The grid keeps only the host's stdout, so an exception that kills the host is otherwise
        // invisible in grid.log ("failed to start", exit code 134, nothing else).
        AppDomain.CurrentDomain.UnhandledException += (_, e) => Console.WriteLine($"Unhandled: {e.ExceptionObject}");
        try
        {
            await ServerApplication.Run(builder => builder
                .Configure(args)
                .AddAllStartupActions()
                // Last, so its registrations override the plugins' (see App).
                .AddStartupAction(appBuilder => new Rsmm.Backend.App().Register(appBuilder))
            );
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Host failed: {ex}");
            throw;
        }
    }
}
