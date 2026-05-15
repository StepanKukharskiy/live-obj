// Grasshopper C# script component: direct LLM caller.
//
// Inputs to create:
//   Run          bool
//   Provider     string  ("openai", "anthropic", "openrouter", or "custom")
//   ApiKey       string
//   Model        string
//   Prompt       string
//   SystemPrompt string
//   BaseUrl      string  optional; use for custom/OpenAI-compatible providers
//   Temperature  double
//
// Outputs to create:
//   LiveObj      string
//   RawResponse  string
//   Error        string

using System;
using System.Collections;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Web.Script.Serialization;

private void RunScript(
	bool Run,
	string Provider,
	string ApiKey,
	string Model,
	string Prompt,
	string SystemPrompt,
	string BaseUrl,
	double Temperature,
	ref object LiveObj,
	ref object RawResponse,
	ref object Error)
{
	LiveObj = "";
	RawResponse = "";
	Error = "";

	if (!Run) return;
	if (string.IsNullOrWhiteSpace(ApiKey))
	{
		Error = "Missing ApiKey.";
		return;
	}
	if (string.IsNullOrWhiteSpace(Prompt))
	{
		Error = "Missing Prompt.";
		return;
	}

	try
	{
		string provider = (Provider ?? "openai").Trim().ToLowerInvariant();
		string raw = provider == "anthropic"
			? CallAnthropic(ApiKey, Model, Prompt, SystemPrompt, Temperature)
			: CallOpenAiCompatible(provider, ApiKey, Model, Prompt, SystemPrompt, BaseUrl, Temperature);

		RawResponse = raw;
		LiveObj = StripCodeFence(ExtractText(provider, raw));
	}
	catch (Exception ex)
	{
		Error = ex.Message;
	}
}

private string CallOpenAiCompatible(
	string provider,
	string apiKey,
	string model,
	string prompt,
	string systemPrompt,
	string baseUrl,
	double temperature)
{
	string url = NormalizeBaseUrl(baseUrl);
	if (string.IsNullOrWhiteSpace(url))
	{
		if (provider == "openrouter")
			url = "https://openrouter.ai/api/v1";
		else
			url = "https://api.openai.com/v1";
	}
	if (!url.EndsWith("/")) url += "/";
	url += "chat/completions";

	if (string.IsNullOrWhiteSpace(model))
		model = provider == "openrouter" ? "openai/gpt-4.1-mini" : "gpt-4.1-mini";

	var messages = new List<Dictionary<string, object>>();
	if (!string.IsNullOrWhiteSpace(systemPrompt))
		messages.Add(new Dictionary<string, object> { { "role", "system" }, { "content", systemPrompt } });
	messages.Add(new Dictionary<string, object> { { "role", "user" }, { "content", prompt } });

	var body = new Dictionary<string, object>
	{
		{ "model", model },
		{ "messages", messages },
		{ "temperature", temperature }
	};

	string json = new JavaScriptSerializer().Serialize(body);
	using (var client = new HttpClient())
	{
		client.Timeout = TimeSpan.FromSeconds(120);
		client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
		if (provider == "openrouter")
		{
			client.DefaultRequestHeaders.TryAddWithoutValidation("HTTP-Referer", "https://spellshape.local");
			client.DefaultRequestHeaders.TryAddWithoutValidation("X-Title", "Spellshape Grasshopper");
		}

		var response = client.PostAsync(url, new StringContent(json, Encoding.UTF8, "application/json")).Result;
		string raw = response.Content.ReadAsStringAsync().Result;
		if (!response.IsSuccessStatusCode)
			throw new Exception("LLM request failed: " + (int)response.StatusCode + " " + raw);
		return raw;
	}
}

private string CallAnthropic(
	string apiKey,
	string model,
	string prompt,
	string systemPrompt,
	double temperature)
{
	if (string.IsNullOrWhiteSpace(model))
		model = "claude-3-5-sonnet-latest";

	var body = new Dictionary<string, object>
	{
		{ "model", model },
		{ "max_tokens", 4096 },
		{ "temperature", temperature },
		{ "messages", new object[]
			{
				new Dictionary<string, object> { { "role", "user" }, { "content", prompt } }
			}
		}
	};
	if (!string.IsNullOrWhiteSpace(systemPrompt))
		body["system"] = systemPrompt;

	string json = new JavaScriptSerializer().Serialize(body);
	using (var client = new HttpClient())
	{
		client.Timeout = TimeSpan.FromSeconds(120);
		client.DefaultRequestHeaders.TryAddWithoutValidation("x-api-key", apiKey);
		client.DefaultRequestHeaders.TryAddWithoutValidation("anthropic-version", "2023-06-01");

		var response = client.PostAsync(
			"https://api.anthropic.com/v1/messages",
			new StringContent(json, Encoding.UTF8, "application/json")).Result;
		string raw = response.Content.ReadAsStringAsync().Result;
		if (!response.IsSuccessStatusCode)
			throw new Exception("Anthropic request failed: " + (int)response.StatusCode + " " + raw);
		return raw;
	}
}

private string ExtractText(string provider, string rawJson)
{
	var serializer = new JavaScriptSerializer();
	var root = serializer.DeserializeObject(rawJson) as Dictionary<string, object>;
	if (root == null) return rawJson;

	if (provider == "anthropic")
	{
		object contentObj;
		if (!root.TryGetValue("content", out contentObj)) return rawJson;
		var content = contentObj as object[];
		if (content == null) return rawJson;
		var sb = new StringBuilder();
		foreach (object item in content)
		{
			var dict = item as Dictionary<string, object>;
			if (dict == null) continue;
			object text;
			if (dict.TryGetValue("text", out text) && text != null)
				sb.Append(text.ToString());
		}
		return sb.ToString();
	}

	object choicesObj;
	if (!root.TryGetValue("choices", out choicesObj)) return rawJson;
	var choices = choicesObj as object[];
	if (choices == null || choices.Length == 0) return rawJson;
	var first = choices[0] as Dictionary<string, object>;
	if (first == null) return rawJson;

	object messageObj;
	if (!first.TryGetValue("message", out messageObj)) return rawJson;
	var message = messageObj as Dictionary<string, object>;
	if (message == null) return rawJson;

	object contentText;
	return message.TryGetValue("content", out contentText) && contentText != null
		? contentText.ToString()
		: rawJson;
}

private string StripCodeFence(string text)
{
	if (string.IsNullOrWhiteSpace(text)) return "";
	string trimmed = text.Trim();
	if (!trimmed.StartsWith("```")) return trimmed;
	int firstNewline = trimmed.IndexOf('\n');
	int lastFence = trimmed.LastIndexOf("```", StringComparison.Ordinal);
	if (firstNewline >= 0 && lastFence > firstNewline)
		return trimmed.Substring(firstNewline + 1, lastFence - firstNewline - 1).Trim();
	return trimmed;
}

private string NormalizeBaseUrl(string baseUrl)
{
	if (string.IsNullOrWhiteSpace(baseUrl)) return "";
	string url = baseUrl.Trim();
	if (url.EndsWith("/chat/completions", StringComparison.OrdinalIgnoreCase))
		url = url.Substring(0, url.Length - "/chat/completions".Length);
	return url.TrimEnd('/');
}
