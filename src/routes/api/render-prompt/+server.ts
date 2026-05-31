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
};

type Body = {
	liveObjText?: string;
	currentPrompt?: string;
	model?: string;
	apiKey?: string;
	apiUrl?: string;
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

const VISUAL_DIRECTION_SYSTEM_PROMPT = `You are a visual direction agent for generative architecture, cinematic concept art, and short-form animation.

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

The agent must also define a simple story moment that could become a 3-second animation.
The story should be image-native: it must emerge from the geometry, material, atmosphere, light, people, or environment.
Do not invent complicated plot.
Do not make characters more important than the geometry.
The geometry must remain the protagonist.

The 3-second animation idea should include:
- story beat: what changes in the scene
- emotional beat: what the viewer should feel
- camera move: how the shot moves over 3 seconds
- geometry action: how the architecture participates
- atmosphere action: light, fog, rain, dust, wind, reflections, birds, fabric, water, etc.
- foreground action: small human or environmental movement for scale
- loop potential: whether it can loop smoothly

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
  }
}

Rules:
- Output only one primary direction.
- The primary direction must be specific, not generic.
- If the user provides draft guidance, treat it as creative intent to expand, clarify, and art-direct.
- Preserve concrete user constraints from draft guidance unless they conflict with the Live OBJ geometry.
- If the user provides no draft guidance, choose the strongest direction from the scene metadata alone.
- Supporting references are optional and must be limited to 3 maximum.
- The story must be readable in a still image and expandable into a 3-second animation.
- The animation must have one simple visual change, not a complex sequence.
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

	const userPrompt = `Analyze this Live OBJ scene as the visual source of truth.

Scene object summary:
${sceneSummary}

Live OBJ metadata:
${sceneMetadata}

Draft user guidance from the render prompt field:
${currentPrompt || '(empty - start from scratch)'}

If draft guidance is present, expand it into a complete image prompt while keeping the geometry as the protagonist. If the draft guidance is empty, start from the Live OBJ scene alone.

Choose one strong visual direction and return the required JSON object.`;

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
