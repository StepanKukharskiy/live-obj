import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import {
	parseStructuredJson,
	requestChatCompletion,
	withLlmRequestOverrides
} from '$lib/server/llm/chat';
import { summarizeLiveObjForPlanning } from '$lib/server/liveObj/iterative';
import { stripCodeFences } from '$lib/server/liveObj/pipeline';

const DEFAULT_MODEL = 'gpt-5.5';
const MAX_METADATA_CHARS = 18_000;

type VisualDirection = {
	geometry_read?: {
		dominant_geometry?: string;
		geometry_personality?: string;
		main_character?: string;
	};
	primary_direction?: {
		name?: string;
		type?: string;
		why_this_is_the_right_direction?: string;
		visual_principle?: string;
		supporting_references?: string[];
		trend_relevance?: string;
		camera_and_composition?: string;
		color_and_light?: string;
		material_and_detail?: string;
		scene_description?: string;
		negative_direction?: string;
		prompt_ready_direction?: string;
	};
	story_for_image_and_3s_animation?: {
		story_title?: string;
		story_beat?: string;
		emotional_beat?: string;
		camera_move_3s?: string;
		geometry_action?: string;
		atmosphere_action?: string;
		foreground_action?: string;
		loop_potential?: string;
		animation_prompt?: string;
		still_image_prompt_addition?: string;
	};
	reel_copy?: {
		story_mode?: string;
		title?: string;
		opening_label?: string;
		opening_line?: string;
		concept?: string;
		references_title?: string;
		reference_line?: string;
		references?: string[];
		process_title?: string;
		process_steps?: string[];
		structure_title?: string;
		ending_label?: string;
		ending?: string;
	};
	shot_plan?: {
		aspect_ratio?: string;
		frames?: Array<{
			label?: string;
			purpose?: string;
			view?: string;
			camera_direction?: number[];
			focus_objects?: string[];
			framing?: string;
		}>;
		pair_prompts?: Array<{
			from?: number;
			to?: number;
			prompt?: string;
		}>;
	};
};

type Body = {
	liveObjText?: string;
	currentPrompt?: string;
	currentDirectionJson?: string;
	timelineCameraContext?: TimelineCameraContext[];
	model?: string;
	apiKey?: string;
	apiUrl?: string;
};
type CameraSnapshot = {
	projection?: string;
	position?: number[];
	target?: number[];
	up?: number[];
	fov?: number | null;
	zoom?: number | null;
} | null;
type TimelineCameraContext = {
	key?: string;
	label?: string;
	camera?: CameraSnapshot;
};

function metadataFromLiveObj(liveObjText: string): string {
	return liveObjText
		.split(/\r?\n/)
		.map((line) => line.trim())
		.filter((line) => line.startsWith('#@'))
		.join('\n');
}

function truncateForPrompt(value: string): string {
	if (value.length <= MAX_METADATA_CHARS) return value;
	return `${value.slice(0, MAX_METADATA_CHARS)}\n...[truncated]`;
}

function numberList(value: unknown): string {
	if (!Array.isArray(value)) return '';
	const numbers = value.filter(
		(item): item is number => typeof item === 'number' && Number.isFinite(item)
	);
	if (numbers.length !== value.length || numbers.length === 0) return '';
	return `[${numbers.map((item) => Number(item.toFixed(4))).join(', ')}]`;
}

function cameraLines(snapshot: CameraSnapshot): string[] {
	if (!snapshot) return [];
	return [
		`projection=${typeof snapshot.projection === 'string' ? snapshot.projection : 'unknown'}`,
		numberList(snapshot.position) ? `position=${numberList(snapshot.position)}` : '',
		numberList(snapshot.target) ? `target=${numberList(snapshot.target)}` : '',
		numberList(snapshot.up) ? `up=${numberList(snapshot.up)}` : '',
		typeof snapshot.fov === 'number' && Number.isFinite(snapshot.fov)
			? `fov=${Number(snapshot.fov.toFixed(3))}`
			: '',
		typeof snapshot.zoom === 'number' && Number.isFinite(snapshot.zoom)
			? `zoom=${Number(snapshot.zoom.toFixed(3))}`
			: ''
	].filter(Boolean);
}

function timelineCameraPrompt(value: unknown): string {
	if (!Array.isArray(value)) return '';
	const blocks = value
		.map((item, index) => {
			if (!item || typeof item !== 'object') return '';
			const context = item as TimelineCameraContext;
			const lines = cameraLines(context.camera ?? null);
			if (!lines.length) return '';
			const label = context.label?.trim() || context.key?.trim() || `Frame ${index + 1}`;
			return `${label}:\n${lines.join('\n')}`;
		})
		.filter(Boolean);
	if (!blocks.length) return '';
	return `Timeline frame camera context:\n${blocks.join('\n\n')}`;
}

function cleanProviderField(value: string | undefined): string | undefined {
	const cleaned = value?.replace(/[^\t\x20-\xff]/g, '').trim();
	return cleaned || undefined;
}

function normalizeDirection(direction: VisualDirection): VisualDirection {
	const refs = direction.primary_direction?.supporting_references;
	if (Array.isArray(refs) && refs.length > 3) {
		direction.primary_direction = {
			...direction.primary_direction,
			supporting_references: refs.slice(0, 3)
		};
	}
	if (Array.isArray(direction.shot_plan?.frames) && direction.shot_plan.frames.length > 3) {
		direction.shot_plan = {
			...direction.shot_plan,
			frames: direction.shot_plan.frames.slice(0, 3)
		};
	}
	if (
		Array.isArray(direction.shot_plan?.pair_prompts) &&
		direction.shot_plan.pair_prompts.length > 2
	) {
		direction.shot_plan = {
			...direction.shot_plan,
			pair_prompts: direction.shot_plan.pair_prompts.slice(0, 2)
		};
	}
	if (Array.isArray(direction.reel_copy?.references) && direction.reel_copy.references.length > 3) {
		direction.reel_copy = {
			...direction.reel_copy,
			references: direction.reel_copy.references.slice(0, 3)
		};
	}
	if (
		Array.isArray(direction.reel_copy?.process_steps) &&
		direction.reel_copy.process_steps.length > 8
	) {
		direction.reel_copy = {
			...direction.reel_copy,
			process_steps: direction.reel_copy.process_steps.slice(0, 8)
		};
	}
	return direction;
}

function requireString(value: unknown, label: string): string {
	if (typeof value !== 'string' || value.trim() === '') {
		throw new Error(`Visual direction is missing ${label}`);
	}
	return value.trim();
}

function buildRenderPrompt(direction: VisualDirection): string {
	const primary = direction.primary_direction ?? {};
	const story = direction.story_for_image_and_3s_animation ?? {};
	const promptReady = requireString(
		primary.prompt_ready_direction,
		'primary_direction.prompt_ready_direction'
	);
	const stillAddition =
		typeof story.still_image_prompt_addition === 'string'
			? story.still_image_prompt_addition.trim()
			: '';
	const negative =
		typeof primary.negative_direction === 'string' ? primary.negative_direction.trim() : '';
	const parts = [promptReady];
	if (stillAddition) parts.push(stillAddition);
	if (negative) parts.push(`Avoid: ${negative}`);
	parts.push(
		'Keep the existing scene geometry as the protagonist; preserve silhouette, object count, proportions, and spatial relationships.'
	);
	return parts.join('\n\n');
}

const VISUAL_DIRECTION_SYSTEM_PROMPT = `You are a visual direction agent for generative architecture, cinematic concept art, and viral short-form animation.

Your task is to analyze an image, sketch, object, massing model, or text prompt and choose ONE primary visual direction that makes the geometry the main character.

The primary direction can be:
- a movie
- a director
- a cartoon / animation
- a place
- a cultural tradition
- a building typology
- an art movement
- an architect
- a sculpture / installation reference
- a game world
- a graphic style
- a material culture reference
- a ritual / festival / craft tradition

Do not produce multiple directions.
Do not list many unrelated references.
Do not create a moodboard dump.

Choose the clearest and strongest visual idea for the geometry.

The agent must also define a coherent short visual story that could become a 3-frame image sequence and a 3-second animation.
The story should be image-native: it must emerge from the geometry, material, atmosphere, light, people, or environment.
Do not invent complicated plot.
Do not make characters more important than the geometry.
The geometry must remain the protagonist.

For the animation idea, prefer a watchable mini-arc over a disconnected wow shot.
The three frames should behave like a tiny storyboard: setup, surprising turn, payoff.
The motion can be surreal, magical, funny, uncanny, or physically impossible, but it must stay causally connected to the previous frame and resolve into a satisfying final image.
Good animation beats include: facades blooming into signs, columns liquefying because the structure is waking up, cars melting into chrome streams that reveal a path, windows becoming eyes that trigger the lighting change, architecture swallowing the sun and snapping into night, roofs turning into birds or butterflies that reveal the silhouette, furniture inflating into a usable object, shadows becoming characters that guide scale, material switching states as a clear before/after, or a day-to-night snap with a motivated reveal.
Avoid generic cinematic motion like only dolly, pan, orbit, fog drift, particles, or parallax unless paired with a concrete story action.
Avoid abstract spectacle where each shot is only "more intense" than the previous one. The viewer should understand why the image changes and want to watch the sequence to its end.

The 3-second animation idea should include:
- story beat: the setup, surprising turn, and payoff of the visual arc
- emotional beat: what the viewer should feel
- camera move: how the shot moves over 3 seconds
- geometry action: how the architecture transforms, reacts, or performs while preserving continuity
- atmosphere action: light, fog, rain, dust, wind, reflections, birds, fabric, water, etc.
- foreground action: small human or environmental movement for scale
- loop potential: whether the final payoff can snap, reverse, or loop memorably

Use current visual trends only as a secondary filter, not as the main output.
Do not hardcode trends. Mention a trend only if it makes the selected direction more visually relevant or shareable.

Output format:

{
  "geometry_read": {
    "dominant_geometry": "",
    "geometry_personality": "",
    "main_character": ""
  },
  "primary_direction": {
    "name": "",
    "type": "",
    "why_this_is_the_right_direction": "",
    "visual_principle": "",
    "supporting_references": [],
    "trend_relevance": "",
    "camera_and_composition": "",
    "color_and_light": "",
    "material_and_detail": "",
    "scene_description": "",
    "negative_direction": "",
    "prompt_ready_direction": ""
  },
  "story_for_image_and_3s_animation": {
    "story_title": "",
    "story_beat": "",
    "emotional_beat": "",
    "camera_move_3s": "",
    "geometry_action": "",
    "atmosphere_action": "",
    "foreground_action": "",
    "loop_potential": "",
    "animation_prompt": "",
    "still_image_prompt_addition": ""
  },
  "reel_copy": {
    "story_mode": "reference_recipe",
    "title": "",
    "opening_label": "Project reveal",
    "opening_line": "",
    "concept": "",
    "references_title": "Visual recipe",
    "reference_line": "",
    "references": [],
    "process_title": "Agent build",
    "process_steps": [],
    "structure_title": "Generated scene",
    "ending_label": "Final output",
    "ending": ""
  },
  "shot_plan": {
    "aspect_ratio": "16:9",
    "frames": [
      {
        "label": "Story setup",
        "purpose": "Establish the geometry, visual direction, and the question the viewer will follow",
        "view": "low_front_3q",
        "camera_direction": [-1, 0.55, -1],
        "focus_objects": [],
        "framing": "full object with breathing room"
      },
      {
        "label": "Surprising turn",
        "purpose": "Show the first readable change, deformation, or reveal while staying connected to the setup",
        "view": "side_detail",
        "camera_direction": [1, 0.35, -0.75],
        "focus_objects": [],
        "framing": "closer view, still readable as the same object"
      },
      {
        "label": "Payoff frame",
        "purpose": "Resolve the visual story into the strongest final image",
        "view": "high_back_3q",
        "camera_direction": [-0.45, 1.1, 0.65],
        "focus_objects": [],
        "framing": "final reveal silhouette"
      }
    ],
    "pair_prompts": [
      { "from": 0, "to": 1, "prompt": "" },
      { "from": 1, "to": 2, "prompt": "" }
    ]
  }
}

Rules:
- Output only one primary direction.
- The primary direction must be specific, not generic.
- If the user provides draft guidance, treat it as creative intent to expand, clarify, and art-direct.
- Preserve concrete user constraints from draft guidance unless they conflict with the Live OBJ geometry.
- If the user provides no draft guidance, choose the strongest direction from the scene metadata alone.
- Supporting references are optional and must be limited to 3 maximum.
- The story must be readable in the still image and expandable into a coherent 3-frame / 3-second sequence.
- The animation must have a clear arc: setup, surprising turn, payoff. It can include unexpected visuals, deformations, material shifts, or impossible events, but they must form one continuous story.
- The animation_prompt must describe the complete visual arc, not just camera movement and not just an isolated transformation.
- The shot_plan must contain exactly 3 frames designed for this specific geometry and visual direction.
- The shot_plan frames are a storyboard for the final image/video output. Frame 0 sets context, frame 1 changes the situation, and frame 2 pays it off.
- reel_copy is for a 9:16 or 16:9 short-form project reel. It must tell a mini educational story about this exact project, not a generic Spellshape ad.
- reel_copy.story_mode must be one of: reference_recipe, process_breakdown, cinematic_breakdown, design_critique, before_after, same_scene_variations, user_workflow.
- reel_copy.opening_label should be specific, such as "Project reveal", "Motion test", or "Scene payoff". Do not use "Final animation".
- reel_copy.title, opening_line, concept, and ending must be short enough for Instagram or YouTube reels. Use one crisp sentence, 90 characters maximum.
- reel_copy.reference_line is the Visual recipe subheading. Make it one complete sentence, 70 characters maximum, with no ellipsis or list syntax.
- reel_copy.references must list up to 3 short references with a reason for selection, such as "TRON arena - luminous edges" or "brutalist console - heavy silhouette". Each line should teach the viewer what that reference contributes: form, motion, light, material, or mood.
- reel_copy.process_steps must list up to 8 short concrete build beats that can label process screenshots and show the amount of work produced by the agent. Do not mention internal files unless the file structure scene needs it.
- reel_copy should repeat scene roles across projects, not fixed sentences. Avoid reusable marketing slogans.
- reel_copy should feel like a mini design or art note for an educational and entertaining making-of reel: concept first, references second, build logic third, final payoff last.
- reel_copy may mention Spellshape agent only when natural. It must not say Live OBJ, OBJ, metadata, prompt, API, or any internal technical detail.
- Shot views should not be generic defaults. Choose camera directions that fit the object: tall objects can use low/high vertical emphasis, flat objects can use plan/oblique views, products can use hero/detail/reveal, and scenes can use establishing/detail/final reveal.
- camera_direction is an approximate normalized world-space vector [x,y,z] from the object center toward the camera. Use positive y for elevated views and lower y values for eye-level/low views.
- focus_objects may be empty, but if metadata names important objects, use at most 3 exact object ids that should drive framing.
- pair_prompts should describe motion from frame 0 to 1 and frame 1 to 2 as connected story beats, aligned with the shot purposes and selected images.
- The first pair prompt should introduce the motivating change. The second pair prompt should resolve or escalate that change into a final payoff.
- Make the animation more dynamic and surprising than a normal architectural flythrough, but never as random abstract spectacle.
- Keep the surprise aligned with the primary direction. For example: a Memphis style hotel swallows the sun, turns on bright neon signs, then resolves into a nighttime festival facade.
- Preserve visual continuity across pair_prompts: same protagonist geometry, readable object scale, coherent camera intent, and a cause-effect relationship between changes.
- The geometry must remain the protagonist.
- People can appear only as scale, ritual, or foreground motion.
- Do not include trend lists.
- Do not use trends as decoration.
- The final answer should feel like a clear art-director decision, not research notes.
- Return JSON only.`;

export const POST: RequestHandler = async ({ request }) => {
	let body: Body;
	try {
		body = (await request.json()) as Body;
	} catch {
		throw error(400, 'Invalid JSON');
	}

	const liveObjText = stripCodeFences(body.liveObjText ?? '');
	if (!liveObjText.trim()) throw error(400, 'liveObjText is required');

	const model = cleanProviderField(body.model) || DEFAULT_MODEL;
	const reqApiKey = cleanProviderField(body.apiKey);
	const reqApiUrl = cleanProviderField(body.apiUrl);
	const sceneMetadata = truncateForPrompt(
		metadataFromLiveObj(liveObjText) || '(no #@ metadata found)'
	);
	const sceneSummary = summarizeLiveObjForPlanning(liveObjText);
	const currentPrompt = body.currentPrompt?.trim();
	const currentDirectionJson = body.currentDirectionJson?.trim();
	const cameraContext = timelineCameraPrompt(body.timelineCameraContext);

	const userPrompt = `Analyze this Live OBJ scene as the visual source of truth.

Scene object summary:
${sceneSummary}

Live OBJ metadata:
${sceneMetadata}

Draft user guidance from the render prompt field:
${currentPrompt || '(empty - start from scratch)'}

Existing visual direction JSON, if this is a refinement pass:
${currentDirectionJson || '(none)'}

${cameraContext || 'Timeline frame camera context: (no timeline frames selected yet)'}

If draft guidance is present, expand it into a complete image prompt while keeping the geometry as the protagonist. If the draft guidance is empty, start from the Live OBJ scene alone.

Choose one strong visual direction and return the required JSON object. If existing visual direction JSON is provided, preserve its core visual direction and update only what needs to align with the timeline camera context. When timeline camera context is available, treat the selected timeline frames as a storyboard: align shot_plan frames and pair_prompts to those exact frame cameras, preserve visual continuity between frames, and make the two motion prompts read as setup-to-turn and turn-to-payoff instead of unrelated camera moves.`;

	try {
		const llmResult = await withLlmRequestOverrides(
			reqApiKey || reqApiUrl || model ? { apiKey: reqApiKey, apiUrl: reqApiUrl, model } : undefined,
			() =>
				requestChatCompletion({
					messages: [
						{ role: 'system', content: VISUAL_DIRECTION_SYSTEM_PROMPT },
						{ role: 'user', content: userPrompt }
					],
					model,
					label: 'api-render-prompt',
					temperature: 0.4,
					maxTokens: 4000
				})
		);
		const direction = normalizeDirection(parseStructuredJson<VisualDirection>(llmResult.content));
		const prompt = buildRenderPrompt(direction);
		return json({
			prompt,
			direction,
			rawLlm: llmResult.content,
			...(llmResult.usage ? { llmUsage: llmResult.usage } : {})
		});
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(502, `Render prompt generation failed: ${message}`);
	}
};
