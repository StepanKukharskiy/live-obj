// Grasshopper C# script component: Live OBJ/raw OBJ renderer with #@post support.
//
// Inputs to create:
//   LiveObj         string
//   Values         List Access, type object/Generic. Generated controls connect here in order.
//   CreateControls bool   optional button to force a refresh; controls also auto-create when missing
//   RemoveControls bool
//
// Outputs to create:
//   Meshes      List<Mesh>
//   Controls    List<string>
//   ExecutedObj string
//   Warnings    List<string>
//
// Supported today:
//   OBJ cache/raw v/f/o mesh parsing
//   #@params
//   #@controls: slider, seed, toggle, choice/value_list
//   #@post:
//     transform position=[x,y,z] rotation=[rx,ry,rz] scale=[sx,sy,sz]
//     mirror axis=x|y|z
//     array count=n offset=[x,y,z]
//     snap_to_ground axis=x|y|z
//     center_origin axes=xz|xy|yz|xyz

using System.Collections.Generic;
using System.Data;
using System.Drawing;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Grasshopper.Kernel;
using Grasshopper.Kernel.Special;
using Rhino.Geometry;

// Rhino 7 C# component note:
// Do not paste a top-level const into the Script pane. This script uses the
// GeneratedPrefix() helper below so the value can live safely in Overrides.

private void RunScript(
	string LiveObj,
	List<object> Values,
	bool CreateControls,
	bool RemoveControls,
	ref object Meshes,
	ref object Controls,
	ref object ExecutedObj,
	ref object Warnings)
{
	var warnings = new List<string>();
	var scene = ParseLiveObj(LiveObj ?? "", warnings);

	if (RemoveControls)
	{
		RemoveGeneratedControls();
		Component.ExpireSolution(true);
	}

	if (scene.Controls.Count > 0 && (CreateControls || ControlsNeedRefresh(scene.Controls)))
	{
		CreateOrRefreshControls(scene.Controls);
	}

	var overrides = ValuesToOverrides(scene.Controls, Values);
	ApplyOverrides(scene, overrides);

	var meshes = new List<Mesh>();
	foreach (var obj in scene.Objects)
	{
		var mesh = BuildMesh(obj, warnings);
		if (mesh == null) continue;
		ApplyPostOps(mesh, obj, warnings);
		mesh.Normals.ComputeNormals();
		mesh.Compact();
		meshes.Add(mesh);
	}

	Meshes = meshes;
	Controls = scene.Controls.Select(c => c.Display()).ToList();
	ExecutedObj = SerializeMeshes(meshes);
	Warnings = warnings;
}

private class Scene
{
	public readonly List<Obj> Objects = new List<Obj>();
	public readonly List<Control> Controls = new List<Control>();
}

private class Obj
{
	public string Name = "unnamed";
	public int FirstVertexIndex = 1;
	public readonly List<Point3d> Vertices = new List<Point3d>();
	public readonly List<int[]> Faces = new List<int[]>();
	public readonly Dictionary<string, string> Params = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
	public readonly List<Control> Controls = new List<Control>();
	public readonly List<PostOp> PostOps = new List<PostOp>();
}

private class Control
{
	public string ObjectName = "";
	public string Kind = "slider";
	public string Key = "";
	public string Label = "";
	public string Min = "";
	public string Max = "";
	public string Step = "";
	public string[] Options = new string[0];
	public string FullKey { get { return ObjectName + "." + Key; } }
	public string Nick { get { return GeneratedPrefix() + FullKey; } }
	public string Display()
	{
		return FullKey + " [" + Kind + "] " + Label + " min=" + Min + " max=" + Max + " step=" + Step;
	}
}

private class PostOp
{
	public string Command = "";
	public readonly Dictionary<string, string> Args = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
}

private Scene ParseLiveObj(string text, List<string> warnings)
{
	var scene = new Scene();
	Obj current = null;
	string block = "";
	int globalVertex = 0;

	Action flush = () =>
	{
		if (current == null) return;
		if (current.Vertices.Count == 0 && current.Faces.Count == 0 &&
			current.Params.Count == 0 && current.Controls.Count == 0 && current.PostOps.Count == 0) return;
		scene.Objects.Add(current);
		scene.Controls.AddRange(current.Controls);
	};

	foreach (string raw in SplitLines(text))
	{
		string line = raw.Trim();
		if (line.Length == 0) continue;

		Match objectMatch = Regex.Match(line, @"^o\s+(.+)$");
		if (objectMatch.Success)
		{
			flush();
			current = new Obj();
			current.Name = objectMatch.Groups[1].Value.Trim();
			current.FirstVertexIndex = globalVertex + 1;
			block = "";
			continue;
		}

		if (current == null)
		{
			current = new Obj();
			current.FirstVertexIndex = globalVertex + 1;
		}

		if (line.StartsWith("#@"))
		{
			string body = line.Substring(2).Trim();
			if (body.Equals("controls:", StringComparison.OrdinalIgnoreCase))
			{
				block = "controls";
				continue;
			}
			if (body.Equals("post:", StringComparison.OrdinalIgnoreCase))
			{
				block = "post";
				continue;
			}
			if (body.StartsWith("params:", StringComparison.OrdinalIgnoreCase))
			{
				foreach (var kv in ParseCommaKvs(body.Substring("params:".Length)))
					current.Params[kv.Key] = kv.Value;
				block = "params";
				continue;
			}
			if (body.EndsWith(":") && !body.StartsWith("-"))
			{
				block = "";
				continue;
			}
			if (body.StartsWith("- "))
			{
				string item = body.Substring(2).Trim();
				if (block == "controls")
				{
					Control c = ParseControl(current.Name, item);
					if (c != null) current.Controls.Add(c);
				}
				else if (block == "post")
				{
					PostOp op = ParsePost(item);
					if (op.Command.Length > 0) current.PostOps.Add(op);
				}
				else if (block == "params")
				{
					foreach (var kv in ParseCommaKvs(item))
						current.Params[kv.Key] = kv.Value;
				}
				continue;
			}
			if (body.StartsWith("post ", StringComparison.OrdinalIgnoreCase))
			{
				PostOp op = ParsePost(body.Substring("post ".Length));
				if (op.Command.Length > 0) current.PostOps.Add(op);
			}
			continue;
		}

		if (line.StartsWith("v "))
		{
			string[] parts = line.Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
			double x, y, z;
			if (parts.Length >= 4 && TryDouble(parts[1], out x) && TryDouble(parts[2], out y) && TryDouble(parts[3], out z))
			{
				current.Vertices.Add(new Point3d(x, y, z));
				globalVertex++;
			}
			continue;
		}

		if (line.StartsWith("f "))
		{
			var ids = line.Split((char[])null, StringSplitOptions.RemoveEmptyEntries)
				.Skip(1)
				.Select(ParseFaceIndex)
				.Where(i => i > 0)
				.ToArray();
			if (ids.Length >= 3) current.Faces.Add(ids);
		}
	}

	flush();
	return scene;
}

private Control ParseControl(string objectName, string item)
{
	var parts = SplitTopLevelWhitespace(item);
	if (parts.Count == 0) return null;
	var args = ParseSpaceKvs(string.Join(" ", parts.Skip(1)));
	var knownKinds = new HashSet<string>(new[] {
		"slider", "stepper", "toggle", "bool", "boolean", "choice", "value_list",
		"select", "dropdown", "enum", "multi-toggle", "multi_toggle"
	}, StringComparer.OrdinalIgnoreCase);

	string kind = parts[0].Trim().ToLowerInvariant();
	string key;
	if (args.TryGetValue("type", out kind) || args.TryGetValue("kind", out kind))
	{
		kind = kind.Trim().ToLowerInvariant();
		if (!args.TryGetValue("key", out key) && !args.TryGetValue("param", out key) && !args.TryGetValue("name", out key))
			key = parts[0].Trim();
	}
	else if (parts.Count >= 2 && knownKinds.Contains(parts[1].Trim()))
	{
		kind = parts[1].Trim().ToLowerInvariant();
		if (!args.TryGetValue("key", out key) && !args.TryGetValue("param", out key) && !args.TryGetValue("name", out key))
			key = parts[0].Trim();
	}
	else if (!args.TryGetValue("key", out key) && !args.TryGetValue("param", out key) && !args.TryGetValue("name", out key))
	{
		return null;
	}
	if (kind == "enum" || kind == "multi-toggle" || kind == "multi_toggle")
		kind = "choice";
	else if (kind == "stepper")
		kind = "slider";

	string label;
	args.TryGetValue("label", out label);
	string options;
	args.TryGetValue("options", out options);
	if (string.IsNullOrWhiteSpace(options)) args.TryGetValue("values", out options);

	var c = new Control();
	c.ObjectName = objectName;
	c.Kind = kind;
	c.Key = key.Trim();
	c.Label = string.IsNullOrWhiteSpace(label) ? c.Key.Replace("_", " ") : label.Replace("_", " ");
	args.TryGetValue("min", out c.Min);
	args.TryGetValue("max", out c.Max);
	args.TryGetValue("step", out c.Step);
	c.Options = string.IsNullOrWhiteSpace(options)
		? new string[0]
		: options.Split(new[] { ',', '|' }, StringSplitOptions.RemoveEmptyEntries).Select(s => s.Trim()).ToArray();
	return c;
}

private PostOp ParsePost(string item)
{
	var parts = SplitTopLevelWhitespace(item);
	var op = new PostOp();
	if (parts.Count == 0) return op;
	op.Command = parts[0].Trim().ToLowerInvariant();
	foreach (var kv in ParseSpaceKvs(string.Join(" ", parts.Skip(1))))
		op.Args[kv.Key] = kv.Value;
	return op;
}

private Mesh BuildMesh(Obj obj, List<string> warnings)
{
	if (obj.Vertices.Count == 0 || obj.Faces.Count == 0) return null;
	var mesh = new Mesh();
	foreach (Point3d p in obj.Vertices)
		mesh.Vertices.Add(p);

	foreach (int[] face in obj.Faces)
	{
		var local = face.Select(i => i - obj.FirstVertexIndex).ToArray();
		if (local.Any(i => i < 0 || i >= obj.Vertices.Count))
		{
			warnings.Add("Skipped face with out-of-range indices on " + obj.Name + ".");
			continue;
		}
		if (local.Length == 3)
			mesh.Faces.AddFace(local[0], local[1], local[2]);
		else if (local.Length == 4)
			mesh.Faces.AddFace(local[0], local[1], local[2], local[3]);
		else
		{
			for (int i = 1; i < local.Length - 1; i++)
				mesh.Faces.AddFace(local[0], local[i], local[i + 1]);
		}
	}
	return mesh.Faces.Count > 0 ? mesh : null;
}

private void ApplyPostOps(Mesh mesh, Obj obj, List<string> warnings)
{
	foreach (PostOp op in obj.PostOps)
	{
		if (op.Command == "transform")
		{
			Vector3d pos = ParseVec3(GetArg(op, "position", "[0,0,0]"), obj.Params, new Vector3d(0, 0, 0));
			Vector3d rot = ParseVec3(GetArg(op, "rotation", "[0,0,0]"), obj.Params, new Vector3d(0, 0, 0));
			Vector3d scale = ParseVec3(GetArg(op, "scale", "[1,1,1]"), obj.Params, new Vector3d(1, 1, 1));
			var xform = Transform.Scale(Point3d.Origin, scale.X, scale.Y, scale.Z);
			xform = Transform.Rotation(Rhino.RhinoMath.ToRadians(rot.X), Vector3d.XAxis, Point3d.Origin) * xform;
			xform = Transform.Rotation(Rhino.RhinoMath.ToRadians(rot.Y), Vector3d.YAxis, Point3d.Origin) * xform;
			xform = Transform.Rotation(Rhino.RhinoMath.ToRadians(rot.Z), Vector3d.ZAxis, Point3d.Origin) * xform;
			xform = Transform.Translation(pos) * xform;
			mesh.Transform(xform);
		}
		else if (op.Command == "mirror")
		{
			string axis = GetArg(op, "axis", "x").ToLowerInvariant();
			Transform mirror = axis == "y"
				? Transform.Mirror(Plane.WorldZX)
				: axis == "z"
					? Transform.Mirror(Plane.WorldXY)
					: Transform.Mirror(Plane.WorldYZ);
			var copy = mesh.DuplicateMesh();
			copy.Transform(mirror);
			mesh.Append(copy);
		}
		else if (op.Command == "array")
		{
			int count = Math.Max(1, (int)Math.Round(EvalNumber(GetArg(op, "count", "1"), obj.Params)));
			Vector3d offset = ParseVec3(GetArg(op, "offset", "[1,0,0]"), obj.Params, new Vector3d(1, 0, 0));
			var baseMesh = mesh.DuplicateMesh();
			for (int i = 1; i < count; i++)
			{
				var copy = baseMesh.DuplicateMesh();
				copy.Transform(Transform.Translation(offset * i));
				mesh.Append(copy);
			}
		}
		else if (op.Command == "snap_to_ground")
		{
			string axis = GetArg(op, "axis", "z").ToLowerInvariant();
			BoundingBox bb = mesh.GetBoundingBox(true);
			Vector3d move = axis == "x" ? new Vector3d(-bb.Min.X, 0, 0)
				: axis == "y" ? new Vector3d(0, -bb.Min.Y, 0)
				: new Vector3d(0, 0, -bb.Min.Z);
			mesh.Transform(Transform.Translation(move));
		}
		else if (op.Command == "center_origin")
		{
			string axes = GetArg(op, "axes", "xyz").ToLowerInvariant();
			BoundingBox bb = mesh.GetBoundingBox(true);
			Point3d c = bb.Center;
			mesh.Transform(Transform.Translation(
				axes.Contains("x") ? -c.X : 0,
				axes.Contains("y") ? -c.Y : 0,
				axes.Contains("z") ? -c.Z : 0));
		}
		else if (op.Command == "material" || op.Command == "tag")
		{
			// Metadata only.
		}
		else
		{
			warnings.Add("Unsupported #@post op on " + obj.Name + ": " + op.Command);
		}
	}
}

private Dictionary<string, string> ValuesToOverrides(List<Control> controls, List<object> values)
{
	var overrides = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
	if (values == null) return overrides;
	for (int i = 0; i < controls.Count && i < values.Count; i++)
	{
		if (values[i] == null) continue;
		overrides[controls[i].FullKey] = Convert.ToString(values[i], CultureInfo.InvariantCulture);
	}
	return overrides;
}

private void ApplyOverrides(Scene scene, Dictionary<string, string> overrides)
{
	foreach (Obj obj in scene.Objects)
	{
		foreach (Control c in obj.Controls)
		{
			string value;
			if (overrides.TryGetValue(c.FullKey, out value))
				obj.Params[c.Key] = value;
		}
	}
}

private void CreateOrRefreshControls(List<Control> controls)
{
	if (Component == null) return;
	var doc = Component.OnPingDocument();
	if (doc == null) return;
	if (Component.Params.Input.Count < 2) return;

	IGH_Param valuesInput = Component.Params.Input[1];
	valuesInput.RemoveAllSources();
	RemoveGeneratedControls();

	float x = Component.Attributes.Pivot.X - 220;
	float y = Component.Attributes.Pivot.Y;

	for (int i = 0; i < controls.Count; i++)
	{
		Control c = controls[i];
		IGH_DocumentObject goo = CreateControlObject(c);
		if (goo == null) continue;
		goo.NickName = c.Nick;
		goo.Attributes.Pivot = new PointF(x, y + i * 32);
		doc.AddObject(goo, false);

		var param = goo as IGH_Param;
		if (param != null)
			valuesInput.AddSource(param);
	}

	Component.Params.OnParametersChanged();
	doc.ScheduleSolution(10, d => Component.ExpireSolution(false));
}

private bool ControlsNeedRefresh(List<Control> controls)
{
	if (Component == null || Component.Params.Input.Count < 2)
		return false;
	var sources = Component.Params.Input[1].Sources;
	if (sources.Count != controls.Count)
		return true;
	for (int i = 0; i < controls.Count; i++)
	{
		if (sources[i].NickName != controls[i].Nick)
			return true;
	}
	return false;
}

private IGH_DocumentObject CreateControlObject(Control c)
{
	string kind = (c.Kind ?? "").ToLowerInvariant();
	if (kind == "toggle" || kind == "bool" || kind == "boolean")
	{
		var toggle = new GH_BooleanToggle();
		toggle.Name = c.Label;
		toggle.NickName = c.Nick;
		toggle.Value = false;
		toggle.CreateAttributes();
		return toggle;
	}

	if (kind == "choice" || kind == "value_list" || kind == "select" || kind == "dropdown")
	{
		var list = new GH_ValueList();
		list.Name = c.Label;
		list.NickName = c.Nick;
		list.ListItems.Clear();
		foreach (string option in c.Options)
			list.ListItems.Add(new GH_ValueListItem(option, "\"" + option + "\""));
		if (list.ListItems.Count == 0)
			list.ListItems.Add(new GH_ValueListItem("default", "\"default\""));
		list.CreateAttributes();
		return list;
	}

	var slider = new GH_NumberSlider();
	slider.Name = c.Label;
	slider.NickName = c.Nick;
	slider.Slider.Minimum = (decimal)ParseDoubleOr(c.Min, 0);
	slider.Slider.Maximum = (decimal)ParseDoubleOr(c.Max, 1);
	decimal step = (decimal)Math.Abs(ParseDoubleOr(c.Step, 0.01));
	slider.Slider.DecimalPlaces = step >= 1 ? 0 : step >= (decimal)0.1 ? 1 : step >= (decimal)0.01 ? 2 : 3;
	double start = ParseDoubleOr(c.Min, 0);
	slider.SetSliderValue((decimal)start);
	slider.CreateAttributes();
	return slider;
}

private void RemoveGeneratedControls()
{
	if (Component == null) return;
	var doc = Component.OnPingDocument();
	if (doc == null) return;
	var generated = doc.Objects
		.Where(o => o.NickName != null && o.NickName.StartsWith(GeneratedPrefix(), StringComparison.Ordinal))
		.ToList();
	foreach (var obj in generated)
		doc.RemoveObject(obj, false);
}

private string GeneratedPrefix()
{
	return "spellshape:";
}

private Vector3d ParseVec3(string raw, Dictionary<string, string> scope, Vector3d fallback)
{
	if (string.IsNullOrWhiteSpace(raw)) return fallback;
	string s = raw.Trim();
	if (scope.ContainsKey(s)) s = scope[s];
	s = s.Trim();
	if (s.StartsWith("[") && s.EndsWith("]")) s = s.Substring(1, s.Length - 2);
	var parts = SplitTopLevel(s, ',');
	if (parts.Count < 3) return fallback;
	return new Vector3d(EvalNumber(parts[0], scope), EvalNumber(parts[1], scope), EvalNumber(parts[2], scope));
}

private double EvalNumber(string raw, Dictionary<string, string> scope)
{
	if (string.IsNullOrWhiteSpace(raw)) return 0;
	string expr = raw.Trim();
	double direct;
	if (TryDouble(expr, out direct)) return direct;
	string value;
	if (scope.TryGetValue(expr, out value))
		return EvalNumber(value, scope);

	foreach (var kv in scope.OrderByDescending(kv => kv.Key.Length))
	{
		double n;
		if (!TryDouble(kv.Value, out n)) continue;
		expr = Regex.Replace(expr, @"\b" + Regex.Escape(kv.Key) + @"\b", n.ToString(CultureInfo.InvariantCulture));
	}

	try
	{
		object computed = new DataTable().Compute(expr, "");
		return Convert.ToDouble(computed, CultureInfo.InvariantCulture);
	}
	catch
	{
		return 0;
	}
}

private string SerializeMeshes(List<Mesh> meshes)
{
	var sb = new StringBuilder();
	int offset = 1;
	for (int mi = 0; mi < meshes.Count; mi++)
	{
		Mesh mesh = meshes[mi];
		sb.AppendLine("o mesh_" + mi.ToString(CultureInfo.InvariantCulture));
		foreach (Point3f v in mesh.Vertices)
			sb.AppendLine("v " + F(v.X) + " " + F(v.Y) + " " + F(v.Z));
		foreach (MeshFace f in mesh.Faces)
		{
			if (f.IsTriangle)
				sb.AppendLine("f " + (f.A + offset) + " " + (f.B + offset) + " " + (f.C + offset));
			else
				sb.AppendLine("f " + (f.A + offset) + " " + (f.B + offset) + " " + (f.C + offset) + " " + (f.D + offset));
		}
		offset += mesh.Vertices.Count;
	}
	return sb.ToString();
}

private Dictionary<string, string> ParseCommaKvs(string raw)
{
	var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
	foreach (string part in SplitTopLevel(raw, ','))
	{
		int eq = part.IndexOf('=');
		if (eq <= 0) continue;
		map[part.Substring(0, eq).Trim()] = part.Substring(eq + 1).Trim();
	}
	return map;
}

private Dictionary<string, string> ParseSpaceKvs(string raw)
{
	var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
	foreach (string token in SplitTopLevelWhitespace(raw))
	{
		int eq = token.IndexOf('=');
		if (eq <= 0) continue;
		map[token.Substring(0, eq).Trim()] = token.Substring(eq + 1).Trim();
	}
	return map;
}

private List<string> SplitTopLevel(string raw, char separator)
{
	var outParts = new List<string>();
	var sb = new StringBuilder();
	int depth = 0;
	foreach (char ch in raw ?? "")
	{
		if (ch == '[' || ch == '(' || ch == '{') depth++;
		if (ch == ']' || ch == ')' || ch == '}') depth = Math.Max(0, depth - 1);
		if (ch == separator && depth == 0)
		{
			if (sb.ToString().Trim().Length > 0) outParts.Add(sb.ToString().Trim());
			sb.Length = 0;
			continue;
		}
		sb.Append(ch);
	}
	if (sb.ToString().Trim().Length > 0) outParts.Add(sb.ToString().Trim());
	return outParts;
}

private List<string> SplitTopLevelWhitespace(string raw)
{
	var outParts = new List<string>();
	var sb = new StringBuilder();
	int depth = 0;
	foreach (char ch in raw ?? "")
	{
		if (ch == '[' || ch == '(' || ch == '{') depth++;
		if (ch == ']' || ch == ')' || ch == '}') depth = Math.Max(0, depth - 1);
		if (char.IsWhiteSpace(ch) && depth == 0)
		{
			if (sb.ToString().Trim().Length > 0) outParts.Add(sb.ToString().Trim());
			sb.Length = 0;
			continue;
		}
		sb.Append(ch);
	}
	if (sb.ToString().Trim().Length > 0) outParts.Add(sb.ToString().Trim());
	return outParts;
}

private string[] SplitLines(string text)
{
	return (text ?? "").Replace("\r\n", "\n").Replace('\r', '\n').Split('\n');
}

private int ParseFaceIndex(string token)
{
	string head = token.Split('/')[0];
	int i;
	return int.TryParse(head, NumberStyles.Integer, CultureInfo.InvariantCulture, out i) ? i : 0;
}

private string GetArg(PostOp op, string key, string fallback)
{
	string value;
	return op.Args.TryGetValue(key, out value) ? value : fallback;
}

private bool TryDouble(string raw, out double value)
{
	return double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out value);
}

private double ParseDoubleOr(string raw, double fallback)
{
	double value;
	return TryDouble(raw, out value) ? value : fallback;
}

private string F(double value)
{
	return value.ToString("0.########", CultureInfo.InvariantCulture);
}
