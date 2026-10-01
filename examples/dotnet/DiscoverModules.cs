// ClawDog Calculator-Constellation REST API - C# .NET 8 module discovery + filtering.
//
// Demonstrates GET /v1/modules and GET /v1/calculators?module=<uri> (added after
// clawdog-calculator-api PR #46). Uses HttpClient + System.Text.Json.
// No third-party dependencies beyond the .NET 8 BCL.
//
// This file is part of the single quickstart project (no separate .csproj):
// `Program.cs` calls DiscoverModules.RunAsync(...) after its own walkthrough,
// so `dotnet run` executes both. Kept as a static class (not top-level
// statements) so it coexists with Program.cs's entry point in one project.

using System.Net.Http.Json;
using System.Text.Json.Nodes;

internal static class DiscoverModules
{
    public static async Task RunAsync(HttpClient http, string calcUri, string periodUri)
    {
        const string ModuleUri = "urn:sbrm:module:fbt";

        // ---- Step 1: GET /v1/modules ----
        Console.WriteLine("=== GET /v1/modules ===");
        var modules = await http.GetFromJsonAsync<JsonArray>("/v1/modules");
        if (modules is null || modules.Any(m => m is not JsonObject))
            throw new InvalidDataException("Module discovery must be an array of objects");
        if (!modules.OfType<JsonObject>().Any(m =>
            m["module_uri"] is JsonValue uri && uri.TryGetValue<string>(out var name) && name == ModuleUri
            && m["calculators"] is JsonArray calculators
            && calculators.Any(c => c is JsonValue value && value.TryGetValue<string>(out var name) && name == calcUri)))
            throw new InvalidDataException("Module discovery does not advertise the example FBT calculator");
        Console.WriteLine($"Discovered {modules?.Count} modules.\n");

        if (modules is not null)
        {
            foreach (var m in modules)
            {
                if (m is null) continue;
                var calcsList = m["calculators"] as JsonArray;
                var firstThree = calcsList?.Take(3)
                    .Select(c => c?.ToString().Split(':').Last())
                    .Where(s => s is not null);
                var calcsPreview = firstThree is not null
                    ? string.Join(", ", firstThree) + (calcsList?.Count > 3 ? "…" : "")
                    : "";

                Console.WriteLine($"  • {m["module_uri"]}");
                Console.WriteLine($"      label:        {m["label"]}");
                Console.WriteLine($"      jurisdiction: {m["jurisdiction"]}");
                Console.WriteLine($"      calculators:  {calcsList?.Count} ({calcsPreview})");
                Console.WriteLine();
            }
        }

        // ---- Step 2: GET /v1/calculators?module=urn:sbrm:module:fbt ----
        Console.WriteLine($"=== GET /v1/calculators?module={ModuleUri} ===");
        var fbtCalcs = await http.GetFromJsonAsync<JsonArray>(
            $"/v1/calculators?module={ModuleUri}"
        );
        fbtCalcs = RequireCalculator(fbtCalcs, calcUri, periodUri);
        Console.WriteLine($"FBT calculators: {fbtCalcs?.Count}\n");

        if (fbtCalcs is not null)
        {
            foreach (var c in fbtCalcs)
            {
                if (c is null) continue;
                var listedUri = c["calc_uri"]?.ToString();
                var selectionKind = (c["selection"] as JsonObject)?["kind"]?.ToString() ?? "?";
                Console.WriteLine($"  {listedUri} - {selectionKind}");
            }
        }

        Console.WriteLine("\nSelecting a calculator:");
        Console.WriteLine("  Pick in three steps. Module (fbt, div7a or depreciation). Benefit");
        Console.WriteLine("  type is a fact - establish it from what actually happened, testing");
        Console.WriteLine("  the specific FBT types in resolution order before residual. Method:");
        Console.WriteLine("  where a benefit type has more than one valuation method the");
        Console.WriteLine("  selection.kind is election or statutory_default - the method is the");
        Console.WriteLine("  employer's choice, not yours. Compute every method in the group the");
        Console.WriteLine("  records support, present them side by side with the election");
        Console.WriteLine("  provision, and let the employer choose. Never pick the method for them.");
    }

    internal static JsonArray RequireCalculator(JsonArray? calcs, string calcUri, string periodUri)
    {
        if (calcs is null || calcs.Any(c => c is not JsonObject))
            throw new InvalidDataException("Discovery must be an array of calculator objects");
        foreach (var calc in calcs)
        {
            if (calc!["calc_uri"] is JsonValue uri && uri.TryGetValue<string>(out var name)
                && name == calcUri && calc["supported_periods"] is JsonArray periods
                && periods.All(p => p is JsonValue value && value.TryGetValue<string>(out _))
                && periods.Any(p => p!.GetValue<string>() == periodUri))
                return calcs;
        }
        throw new InvalidDataException("Discovery does not advertise the example calculator and period");
    }
}
