// ClawDog Calculator-Constellation REST API - C# .NET 8 quickstart.
//
// A complete discover-then-invoke walkthrough using HttpClient + System.Text.Json.
// No third-party dependencies beyond the .NET 8 BCL. Runs against the live
// production API by default; override with the CLAWDOG_CALC_API_URL environment
// variable to point at a different deployment.
//
// Usage:
//     dotnet run
//
// Environment variables:
//     CLAWDOG_CALC_API_URL    Base URL (default: production Cloud Run URL).
//     CLAWDOG_CALC_TIMEOUT    Per-request timeout in seconds (default: 30).
//     CLAWDOG_CALC_RETRIES    Max retries on 5xx (default: 3).

using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

const string DEFAULT_BASE_URL =
    "https://fbt-calculator-api-8340695160.australia-southeast1.run.app";

const string CalcUri = "urn:sbrm:calculator:fbt:car-operating-cost";
const string PeriodUri = "urn:sbrm:period:fbt:fy2026";

try
{
    string baseUrl = Environment.GetEnvironmentVariable("CLAWDOG_CALC_API_URL") ?? DEFAULT_BASE_URL;
    int timeoutSeconds = int.Parse(Environment.GetEnvironmentVariable("CLAWDOG_CALC_TIMEOUT") ?? "30");
    int maxRetries = int.Parse(Environment.GetEnvironmentVariable("CLAWDOG_CALC_RETRIES") ?? "3");
    if (timeoutSeconds <= 0 || maxRetries < 0)
        throw new ArgumentOutOfRangeException("Timeout must be positive; retries must be non-negative");
    Console.WriteLine($"Base URL: {baseUrl}\n");
    using var http = new HttpClient
    {
        BaseAddress = new Uri(baseUrl),
        Timeout = TimeSpan.FromSeconds(timeoutSeconds),
    };
    http.DefaultRequestHeaders.Accept.Add(
        new System.Net.Http.Headers.MediaTypeWithQualityHeaderValue("application/json")
    );

    // ---- Step 1: Discover ----
    Console.WriteLine("=== Step 1 - GET /v1/calculators ===");
    var calcs = await RetryAsync(
        () => http.GetFromJsonAsync<JsonArray>("/v1/calculators"),
        maxRetries
    );
    calcs = DiscoverModules.RequireCalculator(calcs, CalcUri, PeriodUri);
    Console.WriteLine($"Discovered {calcs.Count} calculators.\n");

    foreach (var c in calcs.Cast<JsonObject>().Take(5))
    {
        Console.WriteLine($"  • {c["calc_uri"]}");
        Console.WriteLine($"      label:      {c["label"]}");
        Console.WriteLine($"      method:     {c["method"]}");
        Console.WriteLine($"      periods:    {c["supported_periods"]}");
        Console.WriteLine($"      input ref:  {c["input_schema_ref"]}");
    }
    if (calcs.Count > 5)
    {
        Console.WriteLine($"  … and {calcs.Count - 5} more.\n");
    }
    else
    {
        Console.WriteLine();
    }

    // ---- Step 2: Invoke FBT Car-Operating-Cost ----
    Console.WriteLine(
        $"=== Step 2 - POST /v1/calculators/{CalcUri}/{PeriodUri} ==="
    );

    // A canonical fixture for FBT Car-Operating-Cost. Note the camelCase JSON field
    // names + that businessUsePercentage is on a 0–100 scale (not 0–1).
    // acquisitionCost and openingDepreciatedValue are mutually exclusive - we
    // choose the chained-DV walk path (acquisitionCost + acquisitionDate).
    // See FBTCarOperatingCostInput schema in ../../openapi/clawdog-calculator-api.openapi.json.
    var fixture = new
    {
        businessUsePercentage = 65,
        formOfFinance = "owned",
        fuelRepairsServicing = 8000.00,
        registrationInsurance = 2000.00,
        employeeContribution = 0.00,
        daysHeldInFBTYear = 365,
        acquisitionCost = 45000.00,
        acquisitionDate = "2024-04-01",
    };

    Console.WriteLine(
        $"Request body: {JsonSerializer.Serialize(fixture, new JsonSerializerOptions { WriteIndented = true })}\n"
    );

    var response = await RetryAsync(async () =>
    {
        using var httpResp = await http.PostAsJsonAsync(
            $"/v1/calculators/{CalcUri}/{PeriodUri}", fixture
        );
        httpResp.EnsureSuccessStatusCode();
        var json = await httpResp.Content.ReadAsStringAsync();
        return JsonNode.Parse(json);
    }, maxRetries);
    ValidateCalculation(response);
    Console.WriteLine("Response:");
    Console.WriteLine(response!.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"\n  Taxable value: {response["taxable_value"]}");
    Console.WriteLine($"  Advisory: {response["advisory"]!["disclaimer"]}");

    // ---- Step 3: Module discovery + ?module= filtering (see DiscoverModules.cs) ----
    Console.WriteLine();
    await DiscoverModules.RunAsync(http, CalcUri, PeriodUri);

    Console.WriteLine("\n=== Done ===");
    return 0;
}
catch (Exception error) when (error is HttpRequestException or OperationCanceledException
    or JsonException or InvalidDataException or ArgumentException or FormatException or OverflowException)
{
    Console.Error.WriteLine($"Quickstart failed: {error.Message}");
    return 1;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static void ValidateCalculation(JsonNode? response)
{
    if (response is not JsonObject result || result.ContainsKey("error"))
        throw new InvalidDataException("Calculation must be a result object");
    if (result["taxable_value"] is not JsonValue amount || !amount.TryGetValue<string>(out var text)
        || !Regex.IsMatch(text, @"\A-?[0-9]+\.[0-9]{2}\z"))
        throw new InvalidDataException("Calculation must contain a taxable_value string with two decimal places");
    if (result["advisory"] is not JsonObject advisory || advisory["disclaimer"] is not JsonValue disclaimer
        || !disclaimer.TryGetValue<string>(out var message) || string.IsNullOrWhiteSpace(message))
        throw new InvalidDataException("Calculation must contain an advisory disclaimer");
}

static async Task<T?> RetryAsync<T>(Func<Task<T?>> op, int maxRetries)
{
    ArgumentOutOfRangeException.ThrowIfNegative(maxRetries);
    var random = new Random();
    for (int attempt = 0; ; attempt++)
    {
        try
        {
            return await op();
        }
        catch (HttpRequestException ex)
            when (ex.StatusCode is HttpStatusCode code
                  && (int)code >= 500
                  && (int)code < 600
                  && attempt < maxRetries)
        {
            var delaySeconds =
                Math.Pow(2, attempt) * 0.5
                + random.NextDouble() * Math.Pow(2, attempt) * 0.5;
            Console.Error.WriteLine(
                $"  ⚠ HTTP {(int)code}; retry {attempt + 1}/{maxRetries} in {delaySeconds:F2}s"
            );
            await Task.Delay(TimeSpan.FromSeconds(delaySeconds));
        }
    }
}
