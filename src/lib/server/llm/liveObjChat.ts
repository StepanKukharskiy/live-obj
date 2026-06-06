import type {
	ChatCompletionMessage,
	ChatContentPart,
	ChatMessageContent,
	TokenUsage
} from './chat';
import { requestChatCompletion, streamChatCompletion } from './chat';
import { LIVE_OBJ_SYSTEM_PROMPT, LLM_ONLY_SYSTEM_PROMPT } from './liveObjSystemPrompt';
import type { IterativeControlSpec } from '$lib/server/liveObj/iterative';

const DEFAULT_LIVE_OBJ_MODEL = 'gpt-5.5';

const IMAGE_ONLY_USER_HINT = 'Generate or update the Live OBJ scene from this reference image.';
const SURGICAL_HISTORY_ASSISTANT_PLACEHOLDER =
	'Previous Live OBJ revision was applied. The current Live OBJ in the latest user message is the source of truth.';
const LIVE_OBJ_GENERATION_QUALITY_HINT = `Executor quality guidance:
- For limbs, hoses, fingers, and organic connecting forms, SDF capsules are supported and should render as continuous geometry.
- Do not add smooth immediately after a CAD/kernel bevel on primitive boxes or cylinders; the bevel already rounds those edges and extra smoothing can weaken crisp assembled parts.
- Use #@hidden: true for construction curves, contours, cutters, guide paths, and sweep/loft input objects that should remain editable in source but not render in the scene. Do not use visibility as an op.
- #@source: recipe is supported. For contained ornamental paths, field-traced strands, scattered modules, WFC-like tile layouts, cellular volumes, panelized shells, and expressive sheet/ribbon surfaces, prefer a #@recipe: block using boundary, curve, points, field, trace_field, module, socket, grid, scatter, wfc, instance, iterate, path_formula, surface_formula, perforate_surface, panelize_surface, emit_surface, emit_tubes, emit_volume, and emit_panels instead of hand-authoring many raw curves or vertices. For WFC facades/maps, use semantic modules plus directional sockets such as east/west/north/south, optional force=x,y:tile pins, and #@controls: sliders/selects for important #@params. Recipe objects that emit visible geometry should not be hidden.`;
const LIVE_OBJ_IMAGE_GENERATION_BUDGET_HINT = `Image-to-scene budget:
- Start with a simplified modular 3D interpretation, not a full pixel-by-pixel reconstruction.
- Keep the first-pass scene compact: target roughly 12-35 semantic objects.
- For repeated windows, rooms, capsules, balconies, panels, columns, blocks, or floors, use arrays, paired objects, or a small number of representative modules instead of enumerating every visible instance.
- Capture the main massing, proportions, colors, material families, and distinctive motifs first.
- Avoid dense per-window/per-brick/per-cell geometry unless the user explicitly asks for exhaustive detail.
- Begin the response immediately with #@scene or #@live_obj_version; do not spend output budget on planning text.`;
const RAW_OBJ_IMAGE_GENERATION_BUDGET_HINT = `Image-to-raw-OBJ budget:
- Make a compact direct-mesh interpretation of the reference image, not an exhaustive mesh reconstruction.
- Target roughly 8-24 semantic object groups with direct v/f mesh.
- Use simplified silhouettes, major volumes, representative facade/window/detail groups, and clear object names.
- Do not hand-author every repeated window, panel, brick, cell, or ornament.
- Prefer fewer larger mesh objects with #@semantic hints over hundreds of tiny objects or very large vertex lists.
- Begin the response immediately with #@live_obj_version; do not spend output budget on planning text.`;

const LIVE_OBJ_SURGICAL_EDIT_SYSTEM_PROMPT = `You are a surgical editor for Live OBJ files.

Live OBJ is OBJ plus #@ metadata. The #@ metadata is the editable source of truth; v/f mesh lines are cache output.

Your job:
- Read the current Live OBJ exactly as provided.
- Satisfy the user request with the smallest useful text edits.
- Preserve all unrelated text byte-for-byte.
- Never rewrite the whole scene for a visual feedback/repair pass. Patch only the named object blocks or lines that need repair.
- If a repair can be done by moving, lowering, trimming, narrowing, or deleting one conflicting object, do that instead of regenerating surrounding objects.
- Edit #@ metadata first. Do not add or regenerate v/f cache lines for procedural, SDF, assembly, or simulation objects.
- Keep existing object IDs, units, up axis, kernel settings, params, materials, anchors, and comments unless the user asked to change them.
- For modifications, replace the smallest exact line or object block that contains the change.
- For additions, insert a new object block near the relevant object or append it after the last object by replacing a unique nearby exact snippet with itself plus the new block.
- For removals, replace only the relevant object block with an empty string. If removing a material preset that is no longer used, remove only that preset line.
- If an assembly child list or parent relationship must change, update the smallest relevant #@children/#@parent/#@params lines too.
- When the user asks to mirror/duplicate an existing object to create a second one in the scene, create a distinct nearby instance with new object IDs and a transform/offset. Do not rely only on #@ops mirror unless the user explicitly wants symmetric geometry inside the same object.
- Use only supported Live OBJ metadata patterns already present in the file, plus common supported sources: procedural, llm_mesh, assembly, sdf, simulation, recipe.
- Use #@ops: lists, not #@op: lines.
- Use #@hidden: true for construction curves, contours, cutters, guide paths, and sweep/loft input objects that should remain editable in source but not render in the scene. Do not use visibility as an op.

Return only JSON with this exact shape:
{
  "summary": "short edit summary",
  "edits": [
    {
      "find": "exact text from the current Live OBJ",
      "replace": "replacement text"
    }
  ]
}

Rules for JSON edits:
- Every find string must appear exactly once in the current Live OBJ at the moment that edit is applied.
- The replace string may contain the find string when inserting before or after it.
- Use \\n for newlines inside JSON strings.
- Do not include Markdown, code fences, comments, or explanations outside the JSON.`;

const LIVE_OBJ_CHAT_MESSAGE_SYSTEM_PROMPT = `You write short, specific assistant chat messages for a 3D authoring app.

The 3D source has already been created or edited. Your job is only to describe what changed.

Rules:
- Write one concise sentence.
- Mention the concrete object or parts created/changed when the data makes that clear.
- For iterative edits, emphasize the requested addition/removal/adjustment and do not imply unrelated existing objects were recreated.
- Do not mention Live OBJ, JSON, patches, metadata, executor, source files, or implementation details.
- Do not apologize.
- Do not add a follow-up question.
- Output plain text only.`;

const LIVE_OBJ_ITERATIVE_PLAN_SYSTEM_PROMPT = `You are the planner for an AI-native Live OBJ modeling pipeline.

Decompose the requested scene into a build queue of semantic parts. Do not generate geometry.
The next system stage will ask for each part as a separate Live OBJ object/group and append it to the scene.

Return only JSON with this shape:
{
  "scene": "short scene description",
  "units": "meters",
  "up": "y",
  "visual": {
    "backgroundColor": "#202124",
    "ambientLightIntensity": 0.9,
    "directionalLightIntensity": 1.8,
    "cameraFov": 45,
    "toneMappingExposure": 1.05,
    "canvasAspectRatio": "16:9",
    "cameraView": "front_left_high",
    "cameraFocus": ["primary_object_id"]
  },
  "materials": [
    { "id": "material_id", "color": "#RRGGBB", "roughness": 0.7, "metalness": 0, "role": "short role" }
  ],
  "parts": [
    {
      "id": "stable_object_or_group_id",
      "role": "what this part contributes",
      "method": "llm_mesh",
      "postProcess": {
        "type": "none|uv_dream",
        "prompt": "surface detail intent for this part only",
        "mode": "displace|map-remesh",
        "amount": 1
      },
      "dependencies": ["prior_part_id"],
      "cameraFocus": ["this_part_id", "supporting_part_id"],
      "prompt": "specific instructions for generating only this part",
      "controls": [
        { "key": "part_width", "label": "Part width", "kind": "slider", "default": 1, "min": 0.5, "max": 1.8, "step": 0.05 }
      ],
      "controlPostOps": [
        "transform scale=[part_width,1,1] pivot=[0,0,0]"
      ],
      "validationHints": ["bbox/contact/detail expectations"]
    }
  ],
  "notes": ["global composition notes"]
}

Planning rules:
- Prefer 5-8 parts for rich scenes; fewer for simple objects.
- First pass should be compact semantic massing: major ground/support, primary structure, main envelope/shell, major infill/openings, and one restrained interior/context part only when important.
- Build from coarse support/massing to envelope, structure, major infill, then one optional accent/detail part.
- Merge related elements into one part instead of producing many small parts.
- Do not plan separate first-pass parts for seams, fasteners, bolts, handles, bollards, expansion joints, connection plates, tiny context objects, or micro facade details unless the user explicitly asks for them.
- Make dependencies explicit so later parts can align to earlier geometry.
- Use y as the vertical/up axis unless the user explicitly asks otherwise.
- Use "visual" for scene-level render direction when the request implies a mood, product shot, video, cinematic framing, or social format. Omit visual fields you are not confident about.
- Allowed canvasAspectRatio values: "fill", "1:1", "4:3", "16:9", "9:16", "4:5", "3:2", "2:3", "21:9".
- Allowed cameraView values: "front_left_high", "front_right_high", "low_front", "side", "top", "isometric". Choose a view that supports the requested shot direction.
- Use cameraFocus on visual or parts when a shot/screenshot should frame specific objects. Values must be existing/planned object ids from parts/dependencies, not prose.
- Plan raw mesh parts. Each part method must be "llm_mesh".
- Do not use method values "procedural", "recipe", or "hybrid" in this iterative raw OBJ planner.
- Do not invent executor operations. The default generation method is llm_mesh with semantic metadata and optional generic post notes.
- Decide per part whether it needs an AI dreamed surface post-process. If the base mesh should remain simple but the final part needs hallucinated surface relief, ornamental flow, fabric-like folds, cloud/smoke/water/petal detail, or other image-imagined micro/mid-scale geometry, set postProcess.type to "uv_dream" for that part. Otherwise set type to "none" or omit postProcess.
- Use uv_dream sparingly: usually only the primary shell/body/roof/skin/surface part, not supports, context, lights, cords, fasteners, or already-small details.
- For uv_dream postProcess, write a part-specific prompt that describes only the surface relief to generate while preserving the base mesh volume and silhouette. Use mode "displace" unless the user explicitly needs map-derived topology; use "map-remesh" only for clean topology experiments.
- If the user asks for controls, sliders, parameters, adjustable dimensions, or editability, preserve that requirement in the relevant part prompts. Do not treat metadata controls as forbidden UI objects.
- In raw-first generation, controls are optional but useful when they preserve the authored shape. Add at most 1-2 structured "controls" and "controlPostOps" for a part when the requested edit is safely expressible as a post operation without distorting fitted raw mesh details.
- Prefer neutral multiplier controls with default 1, such as part_scale, relief_amount, smoothing, count, spacing, or placement offsets. Do not use final authored dimensions directly as scale values.
- Do not describe controls in prose inside "prompt". Put all control keys, ranges, defaults, and post ops in the structured fields.
- Every emitted control key should be referenced by at least one executable controlPostOps entry.
- controlPostOps entries must be #@post op bodies without "#@ -" prefixes, such as "transform scale=[part_width,part_height,part_depth] pivot=[0,0,0]", "smooth iterations=smooth_iterations strength=0.35", or "array count=module_count offset=[module_spacing,0,0] centered=true".
- Use only supported raw #@post ops in controlPostOps: transform, symmetrize, mirror, array, deform, subdivide, smooth, simplify, face_lattice, skin_edges, snap_to_ground, center_origin, material, and tag.
- Use stable snake_case ids.`;

const LIVE_OBJ_ITERATIVE_PART_SYSTEM_PROMPT = `You generate one Live OBJ part for an iterative scene builder.

Return only OBJ/Live OBJ text for the requested part. Do not return JSON, Markdown, a scene header, or explanations.

Critical OBJ indexing rule:
- Use local vertex numbering in your returned part. The first vertex you emit is v 1 for face purposes.
- Face lines must reference only vertices defined in this returned part, starting at 1.
- The server will remap indices when appending to the full scene.

Part rules:
- Usually use #@source: llm_mesh for the generated object/group.
- Include #@editable, #@semantic, #@part_of, and #@depends_on metadata where useful.
- Use material names from the plan/current scene; include #@material_preset lines before the first object only if a needed material is missing.
- Generate only the requested part, not the whole scene.
- Fit the part to the existing scene summary and dependencies.
- Use y as the vertical/up axis unless the current scene summary says otherwise.
- Keep geometry compact and clean: target 20-90 vertices for ordinary parts and at most about 160 vertices for a main shell/roof. Use simple topology for the first pass; use supported smoothing/refinement metadata when a softer surface is intended.
- Match topology to visible intent: if the requested visual property cannot be produced by supported executable metadata, represent it with real geometry rather than only names, tags, semantic text, materials, or non-executable notes.
- Prefer quads and simple polygons. Avoid dense grids, seam networks, individual fasteners, tiny bolts, repeated micro-panels, or context clutter in the first pass.
- Prefer one named object per requested part. Use multiple named objects only when the part naturally has a few major sub-parts.
- Add #@post comments only as generic refinement intent; do not invent custom executor ops.`;

const RAW_OBJ_ITERATIVE_PART_SYSTEM_PROMPT = `You generate one raw OBJ part for an iterative scene builder.

Return only OBJ text for the requested part. Do not return JSON, Markdown, a scene header, or explanations.

Critical OBJ indexing rule:
- Use local vertex numbering in your returned part. The first vertex you emit is v 1 for face purposes.
- Face lines must reference only vertices defined in this returned part, starting at 1.
- The server will remap indices when appending to the full scene.

Raw-first part rules:
- Use #@source: llm_mesh for the generated object/group.
- Include #@editable, #@semantic, #@part, #@part_of, and #@depends_on metadata where useful.
- Use #@bbox: min=[x,y,z] max=[x,y,z] when the intended extents are clear.
- Use #@lock: footprint, position, silhouette, material when future edits should preserve those properties.
- Use #@anchor: id=anchor_id at=[x,y,z] for meaningful connection, contact, edge, support, hinge, or alignment points.
- Use #@constraint: as soft edit intent only, such as roof must_touch walls or object must_rest_on_ground.
- Use #@variant: id=base name="Base" when a generated part is one named concept alternative.
- Generate only the requested part, not the whole scene.
- Fit the part to the existing scene summary and dependencies.
- Use y as the vertical/up axis unless the current scene summary says otherwise.
- Keep geometry compact and clean: target 20-90 vertices for ordinary parts and at most about 160 vertices for a main shell. Use simple topology for the first pass; use #@post smooth/subdivide when a softer surface is intended.
- Match topology to visible intent: if the requested visual property cannot be produced by supported executable #@post syntax, bake it into the raw v/f mesh with enough vertices/faces for the effect to be visible. Do not satisfy visible geometry requests only with object names, #@semantic, #@tag, material names, or unsupported #@post attributes.
- Prefer quads and simple polygons. Avoid dense grids, seam networks, individual fasteners, tiny bolts, repeated micro-panels, or context clutter in the first pass.
- Every raw mesh object or group with vertices must include faces for those vertices. Do not emit vertices-only logs, rings, lattices, supports, or roof members.
- If you create multiple log cylinders or beams in one object, include the side faces and cap faces for every member. Do not list only section rings or endpoints.
- Avoid usemtl-only groups. A group is useful only when it contains renderable faces.
- For materials, prefer #@post material for whole-object assignment. If one object needs multiple materials, put each usemtl immediately before the face block it should color; do not list several usemtl directives before vertices or before a single shared face block.
- Use #@post: for raw-post modifier intent. Supported #@post ops are transform, symmetrize, mirror, array, deform, subdivide, smooth, simplify, face_lattice, skin_edges, snap_to_ground, center_origin, material, and tag.
- Use #@post face_lattice when the user asks for cleaner panel or product-like lattice surfaces from a sculpted mesh. It welds the guide mesh first, can pre-fair it with guide_subdivide=n and guide_smooth=n for more even panel sizes and fewer inherited edge valleys, insets each face, extrudes the frame thickness using shared outer offset vertices, omits internal partition walls along source edges shared by adjacent faces, can Catmull-Clark subdivide the result with subdivide=n, and replaces the guide mesh by default.
- Use #@post skin_edges when the user asks for a single continuous printable exoskeleton/wireframe skin around mesh edges. Prefer edges=feature angle=25 to avoid triangulation diagonals, with radius and resolution exposed as params only when useful. Use mode=replace unless the original sculpt should remain visible.
- For repeated modules, #@post array supports per-copy expressions in scale, position, and pivot using i, index, step, count, t, sin(), cos(), min(), max(), abs(), sqrt(), pi, and tau.
- For per-vertex edits, #@post deform supports position=[x,y,z] expressions with x/y/z, normalized u/v/w bbox coordinates, i/index, t, vertex_count, params, and the same math functions.
- Prefer #@post symmetrize for bilaterally symmetric forms and #@post smooth/subdivide for fluid surfaces.
- If the user request, plan, or part prompt asks for controls, include #@params: and #@controls: metadata for meaningful dimensions. Every control key must be referenced by executable #@post metadata such as transform, array, mirror/symmetrize, smooth, subdivide, simplify, snap_to_ground, or center_origin. For raw v/f meshes, use controls for object-level scale, height, spacing, count, smoothing, or placement rather than pretending baked vertex coordinates are parametric.
- In raw-first generation, #@params and #@controls are optional by default. Add at most 1-2 controls when there are safe post modifiers that preserve the authored mesh intent.
- For scale controls on raw meshes, prefer neutral multiplier defaults such as scale=1. Do not use final authored dimensions such as body_width/body_height/body_length directly as transform scale values.
- Parameter references in #@post expressions must use bare names such as voxel_size or (voxel_size*grid_width)/10. Never use template placeholder syntax such as dollar-brace or curly-brace parameter wrappers.
- Put material and tag assignments inside #@post blocks. Do not use #@ops in raw-first mode.
- Always use block syntax: #@post: then lines like #@ - material name=mat_id. Do not emit inline #@post material id=... lines.`;

export const RAW_OBJ_CONTROL_REPAIR_SYSTEM_PROMPT = `You repair one raw OBJ part for the Spellshape raw OBJ renderer.

Return only complete OBJ text for the same part. Do not return Markdown or explanations.
Preserve the object's geometry, object names, faces, material intent, and role.
This raw OBJ part has problematic or specifically requested controls that need repair.

Add minimal useful controls using:
#@params: key=value, key=value
#@controls:
#@ - slider key=key label=Readable_label min=a max=b step=c

Rules:
- Add controls only when they are safe and useful for the part.
- Every emitted control key should be referenced by executable #@post metadata.
- For raw v/f meshes, useful controls are neutral uniform scale, vertical exaggeration, smoothing, array count/spacing, or placement.
- Do not use final authored dimensions such as body_width/body_height/body_length directly as transform scale values.
- Parameter references in #@post expressions must use bare names such as tree_scale or (voxel_size*grid_width)/10.
- Never use template syntax like \${tree_scale}, {tree_scale}, or \${voxel_size}.
- Do not create controls that only sit in #@params without affecting geometry.
- Keep controls small and practical.`;

export type LiveObjLlmResult = {
	content: string;
	usage?: TokenUsage;
};

function normalizeImageDataUrls(imageDataUrls?: string[]): string[] {
	return [...new Set((imageDataUrls ?? []).map((url) => url.trim()).filter(Boolean))];
}

function recordValue(value: unknown): string | undefined {
	if (typeof value === 'string') return value.trim();
	if (typeof value === 'number' && Number.isFinite(value)) return String(value);
	if (typeof value === 'boolean') return value ? 'true' : 'false';
	return undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function controlSpecsFromPart(part: unknown): IterativeControlSpec[] {
	if (!isRecord(part) || !Array.isArray(part.controls)) return [];
	const controls: IterativeControlSpec[] = [];
	for (const rawControl of part.controls) {
		if (!isRecord(rawControl)) continue;
		const key = recordValue(rawControl.key);
		if (!key || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue;
		const options = Array.isArray(rawControl.options)
			? rawControl.options.map(recordValue).filter((option): option is string => Boolean(option))
			: undefined;
		controls.push({
			key,
			label: recordValue(rawControl.label),
			kind: recordValue(rawControl.kind) ?? 'slider',
			default: recordValue(rawControl.default),
			min: recordValue(rawControl.min),
			max: recordValue(rawControl.max),
			step: recordValue(rawControl.step),
			...(options && options.length > 0 ? { options } : {})
		});
	}
	return controls;
}

function postOpsFromPart(part: unknown, controls: IterativeControlSpec[]): string[] {
	const rawOps = isRecord(part) && Array.isArray(part.controlPostOps) ? part.controlPostOps : [];
	const ops = rawOps
		.map(recordValue)
		.filter((op): op is string => Boolean(op))
		.map((op) =>
			op
				.replace(/^#@\s*post:\s*$/i, '')
				.replace(/^#@\s*-\s*/i, '')
				.replace(/^-\s*/i, '')
				.trim()
		)
		.filter(Boolean);
	void controls;
	return ops;
}

function renderPartControlMetadata(part: unknown): string {
	const controls = controlSpecsFromPart(part);
	if (controls.length === 0) return '';
	const params = controls
		.map((control) => `${control.key}=${recordValue(control.default) ?? '1'}`)
		.join(', ');
	const controlLines = controls.map((control) => {
		const kind = control.kind || 'slider';
		const attrs = [
			`key=${control.key}`,
			`label=${(control.label || control.key).replace(/\s+/g, '_')}`,
			control.min != null ? `min=${control.min}` : '',
			control.max != null ? `max=${control.max}` : '',
			control.step != null ? `step=${control.step}` : '',
			control.options && control.options.length > 0 ? `options=${control.options.join('|')}` : ''
		].filter(Boolean);
		return `#@ - ${kind} ${attrs.join(' ')}`;
	});
	const postOps = postOpsFromPart(part, controls);
	const postLines = postOps.map((op) => `#@ - ${op}`);
	return [
		'Required canonical control metadata for this part:',
		'#@params: ' + params,
		'#@controls:',
		...controlLines,
		'#@post:',
		...postLines,
		'Include this metadata block in the generated object before any v/f geometry. Do not restate it as prose.'
	].join('\n');
}

function userMessageContent(text: string, imageDataUrls?: string[]): ChatMessageContent {
	const t = text.trim();
	const images = normalizeImageDataUrls(imageDataUrls);
	if (images.length === 0) return t;
	const parts: ChatContentPart[] = [
		{ type: 'text', text: t || IMAGE_ONLY_USER_HINT },
		...images.map((url) => ({
			type: 'image_url' as const,
			image_url: { url, detail: 'low' as const }
		}))
	];
	return parts;
}

function surgicalHistoryMessages(history: ChatCompletionMessage[]): ChatCompletionMessage[] {
	return history.slice(-8).map((message) => {
		if (message.role === 'assistant') {
			return { role: 'assistant', content: SURGICAL_HISTORY_ASSISTANT_PLACEHOLDER };
		}
		return message;
	});
}

function surgicalEditUserContent(
	userMessage: string,
	currentLiveObj: string,
	imageDataUrls?: string[]
): ChatMessageContent {
	const request = userMessage.trim() || IMAGE_ONLY_USER_HINT;
	const text = [
		'User request:',
		request,
		'',
		'Current Live OBJ:',
		'```obj',
		currentLiveObj,
		'```',
		'',
		'Return a surgical JSON patch against the Current Live OBJ. Do not return a full Live OBJ file.'
	].join('\n');
	return userMessageContent(text, imageDataUrls);
}

function objectNamesFromLiveObj(sourceText: string): string[] {
	const names = [...sourceText.matchAll(/^\s*o\s+([^\s#]+)/gm)].map((m) => m[1]);
	return [...new Set(names)];
}

function compactList(items: string[], max = 24): string {
	if (items.length <= max) return items.join(', ');
	return `${items.slice(0, max).join(', ')} and ${items.length - max} more`;
}

function chatMessagePrompt(input: {
	userMessage: string;
	previousLiveObj?: string;
	nextLiveObj: string;
	editMode: 'surgical' | 'rewrite';
	surgicalEditSummary?: string;
	rawLlm?: string;
}): string {
	const previousNames = objectNamesFromLiveObj(input.previousLiveObj ?? '');
	const nextNames = objectNamesFromLiveObj(input.nextLiveObj);
	const previousSet = new Set(previousNames);
	const nextSet = new Set(nextNames);
	const added = nextNames.filter((name) => !previousSet.has(name));
	const removed = previousNames.filter((name) => !nextSet.has(name));
	return [
		`User request: ${input.userMessage || IMAGE_ONLY_USER_HINT}`,
		`Mode: ${input.editMode}`,
		input.surgicalEditSummary ? `Model edit summary: ${input.surgicalEditSummary}` : '',
		`Previous object IDs: ${compactList(previousNames) || '(none)'}`,
		`Final object IDs: ${compactList(nextNames) || '(none)'}`,
		`Added object IDs: ${compactList(added) || '(none)'}`,
		`Removed object IDs: ${compactList(removed) || '(none)'}`,
		input.rawLlm && input.editMode === 'surgical'
			? `Raw surgical patch or summary:\n${input.rawLlm.slice(0, 3000)}`
			: '',
		'',
		'Write the assistant chat message now.'
	]
		.filter(Boolean)
		.join('\n');
}

/**
 * Asks the configured LLM for a Live OBJ file using the same system prompt as `src/routes/api/llm`.
 * `history` should be prior user/assistant turns; assistant content should be the previous Live OBJ text.
 */
export async function requestLiveObjFromLlm(
	userMessage: string,
	history: ChatCompletionMessage[],
	model: string = DEFAULT_LIVE_OBJ_MODEL,
	options?: { imageDataUrl?: string; imageDataUrls?: string[]; useProcedural?: boolean }
): Promise<LiveObjLlmResult> {
	const useProcedural = options?.useProcedural !== false;
	const systemPrompt = useProcedural ? LIVE_OBJ_SYSTEM_PROMPT : LLM_ONLY_SYSTEM_PROMPT;
	const imageDataUrls = normalizeImageDataUrls([
		...(options?.imageDataUrls ?? []),
		...(options?.imageDataUrl ? [options.imageDataUrl] : [])
	]);
	const imageHint =
		imageDataUrls.length > 0
			? `\n\n${useProcedural ? LIVE_OBJ_IMAGE_GENERATION_BUDGET_HINT : RAW_OBJ_IMAGE_GENERATION_BUDGET_HINT}`
			: '';
	const messages: ChatCompletionMessage[] = [
		{
			role: 'system',
			content: useProcedural
				? `${systemPrompt}\n\n${LIVE_OBJ_GENERATION_QUALITY_HINT}${imageHint}`
				: `${systemPrompt}${imageHint}`
		},
		...history,
		{ role: 'user', content: userMessageContent(userMessage, imageDataUrls) }
	];
	const maxTokens = 32000;
	const { content, usage } = await requestChatCompletion({
		messages,
		model: model || DEFAULT_LIVE_OBJ_MODEL,
		label: 'live-obj-llm',
		maxTokens,
		timeoutMs: imageDataUrls.length > 0 ? 240000 : undefined
	});
	return { content, usage };
}

/**
 * Asks the configured LLM for exact text edits against the current Live OBJ.
 * The server applies these edits locally, so unrelated source text stays untouched.
 */
export async function requestLiveObjSurgicalPatchFromLlm(
	userMessage: string,
	currentLiveObj: string,
	history: ChatCompletionMessage[],
	model: string = DEFAULT_LIVE_OBJ_MODEL,
	options?: {
		imageDataUrl?: string;
		imageDataUrls?: string[];
		currentSceneMode?: 'live_obj' | 'raw_obj';
	}
): Promise<LiveObjLlmResult> {
	const imageDataUrls = normalizeImageDataUrls([
		...(options?.imageDataUrls ?? []),
		...(options?.imageDataUrl ? [options.imageDataUrl] : [])
	]);
	const modeHint =
		options?.currentSceneMode === 'raw_obj'
			? [
					'Current scene mode: raw OBJ / raw-post output.',
					'Important: existing v/f mesh blocks are source base geometry, not disposable cache. Preserve existing mesh object blocks unless the user asks to replace them.',
					'For cleanup, symmetry, repetition, material, or tag edits on raw OBJ scenes, prefer adding or editing #@post blocks. Do not add #@ops and do not convert the whole scene to procedural metadata.',
					'Supported #@post ops include transform, symmetrize, mirror, array, deform, subdivide, smooth, simplify, face_lattice, skin_edges, snap_to_ground, center_origin, material, and tag.',
					'When adding tunable #@post values, expose them with #@params and #@controls, and make the #@post expressions reference those params.',
					'Use #@post only when the requested visible change is fully expressible with supported executable #@post syntax. Otherwise update the affected raw mesh block or add real geometry; object names, #@semantic, #@tag, material names, and unsupported #@post attributes do not count as implementing visible geometry.'
				].join('\n')
			: [
					'Current scene mode: Live OBJ / tools-on output.',
					'Important: #@ metadata is the editable source of truth; v/f mesh lines are cache output.'
				].join('\n');
	const messages: ChatCompletionMessage[] = [
		{
			role: 'system',
			content:
				imageDataUrls.length > 0
					? `${LIVE_OBJ_SURGICAL_EDIT_SYSTEM_PROMPT}\n\n${LIVE_OBJ_IMAGE_GENERATION_BUDGET_HINT}`
					: LIVE_OBJ_SURGICAL_EDIT_SYSTEM_PROMPT
		},
		...surgicalHistoryMessages(history),
		{
			role: 'user',
			content: surgicalEditUserContent(
				`${modeHint}\n\n${userMessage}`,
				currentLiveObj,
				imageDataUrls
			)
		}
	];
	const { content, usage } = await requestChatCompletion({
		messages,
		model: model || DEFAULT_LIVE_OBJ_MODEL,
		label: 'live-obj-surgical-edit',
		maxTokens: imageDataUrls.length > 0 ? 22000 : 14000,
		timeoutMs: imageDataUrls.length > 0 ? 240000 : undefined
	});
	return { content, usage };
}

export async function requestLiveObjAssistantMessageFromLlm(
	input: {
		userMessage: string;
		previousLiveObj?: string;
		nextLiveObj: string;
		editMode: 'surgical' | 'rewrite';
		surgicalEditSummary?: string;
		rawLlm?: string;
	},
	model: string = DEFAULT_LIVE_OBJ_MODEL
): Promise<LiveObjLlmResult> {
	const { content, usage } = await requestChatCompletion({
		messages: [
			{ role: 'system', content: LIVE_OBJ_CHAT_MESSAGE_SYSTEM_PROMPT },
			{ role: 'user', content: chatMessagePrompt(input) }
		],
		model: model || DEFAULT_LIVE_OBJ_MODEL,
		label: 'live-obj-chat-message',
		maxTokens: 1000,
		timeoutMs: 90000
	});
	return { content: content.replace(/^["'`]+|["'`]+$/g, '').trim(), usage };
}

export async function requestLiveObjPartPlanFromLlm(
	userMessage: string,
	model: string = DEFAULT_LIVE_OBJ_MODEL,
	options?: {
		imageDataUrl?: string;
		imageDataUrls?: string[];
		currentLiveObjSummary?: string;
		useProcedural?: boolean;
	}
): Promise<LiveObjLlmResult> {
	const imageDataUrls = normalizeImageDataUrls([
		...(options?.imageDataUrls ?? []),
		...(options?.imageDataUrl ? [options.imageDataUrl] : [])
	]);
	const prompt = [
		`User request: ${userMessage.trim() || IMAGE_ONLY_USER_HINT}`,
		options?.useProcedural === false
			? [
					'Generation mode: tools-off raw-first OBJ.',
					'Plan ONLY raw mesh parts. Each part method must be "llm_mesh".',
					'Do not use method values "procedural", "recipe", or "hybrid" in this mode.',
					'Controls are optional. Add at most 1-2 controls only for safe post operations such as uniform scale, placement, smoothing, repetition count/spacing, terrain relief, or other modifiers that preserve the authored mesh intent.',
					'If a part could be procedural conceptually, still describe it as direct compact OBJ mesh with optional #@post material/tag/smooth/symmetrize notes.'
				].join('\n')
			: 'Generation mode: Live OBJ with procedural/recipe/raw mesh parts as appropriate.',
		options?.currentLiveObjSummary
			? `Current scene summary:\n${options.currentLiveObjSummary}`
			: 'Current scene summary: (empty scene)',
		options?.currentLiveObjSummary
			? 'If the user request is additive, plan only the new parts to append to the current scene. Do not re-plan existing objects unless the user explicitly asks to replace or rebuild them.'
			: '',
		'',
		'Create the iterative part plan now.'
	].join('\n');
	const { content, usage } = await requestChatCompletion({
		messages: [
			{ role: 'system', content: LIVE_OBJ_ITERATIVE_PLAN_SYSTEM_PROMPT },
			{ role: 'user', content: userMessageContent(prompt, imageDataUrls) }
		],
		model: model || DEFAULT_LIVE_OBJ_MODEL,
		label: 'live-obj-iterative-plan',
		maxTokens: 10000,
		timeoutMs: imageDataUrls.length > 0 ? 180000 : undefined
	});
	return { content, usage };
}

export async function requestLiveObjPartFromLlm(
	input: {
		userMessage: string;
		part: unknown;
		plan?: unknown;
		currentLiveObjSummary: string;
	},
	model: string = DEFAULT_LIVE_OBJ_MODEL,
	options?: { imageDataUrl?: string; imageDataUrls?: string[]; useProcedural?: boolean }
): Promise<LiveObjLlmResult> {
	const imageDataUrls = normalizeImageDataUrls([
		...(options?.imageDataUrls ?? []),
		...(options?.imageDataUrl ? [options.imageDataUrl] : [])
	]);
	const requiredControlMetadata =
		options?.useProcedural === false ? renderPartControlMetadata(input.part) : '';
	const prompt = [
		`Original user request: ${input.userMessage.trim() || IMAGE_ONLY_USER_HINT}`,
		'',
		`Requested part spec:\n${JSON.stringify(input.part, null, 2)}`,
		'',
		input.plan ? `Overall part plan:\n${JSON.stringify(input.plan, null, 2)}` : '',
		'',
		`Current scene summary:\n${input.currentLiveObjSummary || '(empty scene)'}`,
		'',
		requiredControlMetadata,
		'',
		options?.useProcedural === false
			? [
					'Raw OBJ control policy:',
					requiredControlMetadata
						? 'Use the required canonical control metadata block above exactly.'
						: 'Include at most 1-2 #@params: and #@controls: entries when a control is safe and genuinely useful for this part; otherwise omit controls.',
					'Use canonical control syntax:',
					'#@controls:',
					'#@ - slider key=scale label=Scale min=0.5 max=2.0 step=0.05',
					'Every emitted control key should be referenced by executable #@post syntax. Prefer neutral multiplier controls with default 1 for scale, or direct controls for position, array count/offset, deform amount, smooth iterations/strength, simplify ratio, or center_origin.',
					'Do not use final object dimensions such as body_width/body_height/body_length directly as transform scale values on raw meshes that are already authored at those dimensions.',
					'Do not emit unsupported #@post attributes such as target=, origin=, translate=, rotate_y=, axis= for array spacing, or mode=.'
				].join('\n')
			: '',
		JSON.stringify(input.part).includes('"uv_dream"')
			? [
					'UV dream post-process preparation:',
					'The planner marked this part for uv_dream postProcess. Generate a clean low-poly source mesh that preserves the intended base volume and silhouette.',
					'Add #@uv_hint to the object and #@uv_island markers before related face blocks so the later UV unwrap can group surfaces by modelling logic.',
					'For hollow or vessel-like bodies such as vases, cups, lampshades, shells, melted containers, bottles, bowls, and sleeves, use #@uv_hint: strategy=radial seam=back groups=side,top,bottom and group faces as top, bottom, and side rather than front/back/left/right shards.',
					'For vessel/shell/body-like parts, use roles such as side/top/bottom/opening/inner/outer. For architecture skins, use roles such as roof/facade/soffit/edge. For product shells, use semantic roles that match the part.',
					'Do not bake tiny relief into vertices; leave fine folds/flow/texture-like surface detail to the uv_dream post-process.'
				].join('\n')
			: '',
		'',
		'Generate only the requested part now.'
	]
		.filter(Boolean)
		.join('\n');
	const systemPrompt =
		options?.useProcedural === false
			? RAW_OBJ_ITERATIVE_PART_SYSTEM_PROMPT
			: LIVE_OBJ_ITERATIVE_PART_SYSTEM_PROMPT;
	const { content, usage } = await requestChatCompletion({
		messages: [
			{ role: 'system', content: systemPrompt },
			{ role: 'user', content: userMessageContent(prompt, imageDataUrls) }
		],
		model: model || DEFAULT_LIVE_OBJ_MODEL,
		label: 'live-obj-iterative-part',
		maxTokens: 32000,
		timeoutMs: imageDataUrls.length > 0 ? 240000 : 180000
	});
	return { content, usage };
}

export async function streamLiveObjPartFromLlm(
	input: {
		userMessage: string;
		part: unknown;
		plan?: unknown;
		currentLiveObjSummary: string;
	},
	model: string = DEFAULT_LIVE_OBJ_MODEL,
	options: { imageDataUrl?: string; imageDataUrls?: string[]; useProcedural?: boolean } | undefined,
	onDelta: (delta: string) => void | Promise<void>
): Promise<LiveObjLlmResult> {
	const imageDataUrls = normalizeImageDataUrls([
		...(options?.imageDataUrls ?? []),
		...(options?.imageDataUrl ? [options.imageDataUrl] : [])
	]);
	const requiredControlMetadata =
		options?.useProcedural === false ? renderPartControlMetadata(input.part) : '';
	const prompt = [
		`Original user request: ${input.userMessage.trim() || IMAGE_ONLY_USER_HINT}`,
		'',
		`Requested part spec:\n${JSON.stringify(input.part, null, 2)}`,
		'',
		input.plan ? `Overall part plan:\n${JSON.stringify(input.plan, null, 2)}` : '',
		'',
		`Current scene summary:\n${input.currentLiveObjSummary || '(empty scene)'}`,
		'',
		requiredControlMetadata,
		'',
		options?.useProcedural === false
			? [
					'Raw OBJ control policy:',
					requiredControlMetadata
						? 'Use the required canonical control metadata block above exactly.'
						: 'Include at most 1-2 #@params: and #@controls: entries when a control is safe and genuinely useful for this part; otherwise omit controls.',
					'Use canonical control syntax:',
					'#@controls:',
					'#@ - slider key=scale label=Scale min=0.5 max=2.0 step=0.05',
					'Every emitted control key should be referenced by executable #@post syntax. Prefer neutral multiplier controls with default 1 for scale, or direct controls for position, array count/offset, deform amount, smooth iterations/strength, simplify ratio, or center_origin.',
					'Do not use final object dimensions such as body_width/body_height/body_length directly as transform scale values on raw meshes that are already authored at those dimensions.',
					'Do not emit unsupported #@post attributes such as target=, origin=, translate=, rotate_y=, axis= for array spacing, or mode=.'
				].join('\n')
			: '',
		'',
		'Generate only the requested part now.'
	]
		.filter(Boolean)
		.join('\n');
	const systemPrompt =
		options?.useProcedural === false
			? RAW_OBJ_ITERATIVE_PART_SYSTEM_PROMPT
			: LIVE_OBJ_ITERATIVE_PART_SYSTEM_PROMPT;
	const { content, usage } = await streamChatCompletion({
		messages: [
			{ role: 'system', content: systemPrompt },
			{ role: 'user', content: userMessageContent(prompt, imageDataUrls) }
		],
		model: model || DEFAULT_LIVE_OBJ_MODEL,
		label: 'live-obj-iterative-part-stream',
		maxTokens: 32000,
		timeoutMs: imageDataUrls.length > 0 ? 240000 : 180000,
		onDelta
	});
	return { content, usage };
}

export async function requestRawObjControlsRepairFromLlm(
	input: {
		userMessage: string;
		part: unknown;
		plan?: unknown;
		rawPart: string;
		controlIssues: string[];
	},
	model: string = DEFAULT_LIVE_OBJ_MODEL
): Promise<LiveObjLlmResult> {
	const requiredControlMetadata = renderPartControlMetadata(input.part);
	const prompt = [
		`Original user request: ${input.userMessage.trim() || 'Generate the requested raw OBJ part'}`,
		'',
		`Requested part spec:\n${JSON.stringify(input.part, null, 2)}`,
		'',
		input.plan ? `Overall part plan:\n${JSON.stringify(input.plan, null, 2)}` : '',
		'',
		'Control issues:',
		...input.controlIssues.map((issue) => `- ${issue}`),
		'',
		requiredControlMetadata,
		'',
		'OBJ part to repair:',
		input.rawPart
	]
		.filter(Boolean)
		.join('\n');
	const { content, usage } = await requestChatCompletion({
		messages: [
			{ role: 'system', content: RAW_OBJ_CONTROL_REPAIR_SYSTEM_PROMPT },
			{ role: 'user', content: prompt }
		],
		model: model || DEFAULT_LIVE_OBJ_MODEL,
		label: 'raw-obj-controls-repair',
		maxTokens: 32000,
		timeoutMs: 180000
	});
	return { content, usage };
}

export { DEFAULT_LIVE_OBJ_MODEL };
