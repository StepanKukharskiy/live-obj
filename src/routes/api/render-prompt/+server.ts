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
		story_arc?: {
			logline?: string;
			setup?: string;
			turn?: string;
			payoff?: string;
			final_state?: string;
		};
		frames?: Array<{
			label?: string;
			purpose?: string;
			view?: string;
			camera_direction?: number[];
			focus_objects?: string[];
			framing?: string;
			still_prompt?: string;
		}>;
		pair_prompts?: Array<{
			from?: number;
			to?: number;
			role?: 'setup_to_turn' | 'turn_to_payoff';
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
type NormalizedStoryArc = {
	logline: string;
	setup: string;
	turn: string;
	payoff: string;
	final_state: string;
};
type CreativeFallbackRecipe = {
	name: string;
	type: string;
	visualPrinciple: string;
	references: string[];
	trendRelevance: string;
	camera: string;
	colorLight: string;
	materialDetail: string;
	twist: string;
	negative: string;
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

function cleanDirectionText(value: unknown): string {
	return typeof value === 'string' ? value.trim() : '';
}

function compactSentences(parts: string[]): string {
	return parts
		.map((part) => part.trim().replace(/\s+/g, ' '))
		.filter(Boolean)
		.join(' ');
}

function chooseCreativeFallbackRecipe(sourceText: string): CreativeFallbackRecipe {
	const text = sourceText.toLowerCase();
	if (/\b(capsule|shaft|porthole|circular window|console|bracket)\b/.test(text)) {
		return {
			name: 'Soyuz Reliquary Capsule',
			type: 'retro space-age craft ritual',
			visualPrinciple:
				'Treat the preserved capsule geometry like a recovered ceremonial spacecraft, halfway between Soviet engineering and a museum object under ritual light.',
			references: [
				'Soyuz descent module - blunt capsule mass and heat-scarred pragmatism',
				'brutalist utility core - concrete weight around the central shaft',
				'paper lantern festival - warm internal glow through the circular window'
			],
			trendRelevance:
				'The image has a strong short-form hook because the object reads instantly, then rewards inspection with a strange material event.',
			camera:
				'Three-quarter hero view slightly below the circular window, keeping the shaft, shell, brackets, and console legible in one clean silhouette.',
			colorLight:
				'Bone ceramic exterior, soot-dark frame, cold blue glass, and one warm lantern-like pulse from inside; restrained cinematic rim light and soft floor shadows.',
			materialDetail:
				'Matte concrete shaft, satin capsule shell, blackened machined window ring, blue glass with subtle condensation, and tiny heat-stain gradients on bracket edges.',
			twist:
				'The circular window holds a tiny impossible moon; fine kintsugi-like light seams appear across the shell surface without splitting or moving the geometry.',
			negative:
				'Avoid adding extra spacecraft parts, cables, pilots, city backdrops, generic sci-fi panels, heavy smoke, or effects that obscure the exact part relationships.'
		};
	}
	if (/\b(chair|seat|bench|stool|table|console)\b/.test(text)) {
		return {
			name: 'Bauhaus Seance Furniture',
			type: 'design object with ritual performance',
			visualPrinciple:
				'Make the object feel like a functional prototype photographed during an impossible design demonstration.',
			references: [
				'Bauhaus workshop photo - disciplined object clarity',
				'Italian radical design - playful material contradiction',
				'stage magic cabinet - impossible reveal contained inside the form'
			],
			trendRelevance:
				'The contrast between readable product geometry and a single surreal material trick makes the still shareable without losing design intent.',
			camera:
				'Catalog-clean three-quarter product view with one controlled detail highlight and enough negative space to read the full silhouette.',
			colorLight:
				'Neutral studio base with one saturated accent reflection, soft shadow under the object, and crisp edge definition.',
			materialDetail:
				'Keep original material assignments readable while adding tactile grain, bevel highlights, and small fabrication marks.',
			twist:
				'A thin layer of translucent colored resin appears to levitate a few millimeters above the surfaces, mirroring the exact silhouette like an aura.',
			negative:
				'Avoid changing the furniture count, adding props that become the subject, or hiding construction details behind fog or glow.'
		};
	}
	if (/\b(tower|building|facade|window|roof|stairs|wall|column)\b/.test(text)) {
		return {
			name: 'Scarpa Night Procession',
			type: 'architectural ritual still',
			visualPrinciple:
				'Frame the geometry like a precise architectural fragment activated by a quiet civic ceremony.',
			references: [
				'Carlo Scarpa threshold detail - layered joints and reveal light',
				'Obon lantern procession - warm cultural glow and scale',
				'metabolist architecture - modular silhouette with civic strangeness'
			],
			trendRelevance:
				'It gives the scene an immediately legible architectural identity plus one memorable visual rule for motion.',
			camera:
				'Oblique architectural view chosen to preserve the full massing and show the most important named parts.',
			colorLight:
				'Cool structural body, warm lantern reflections, wet ground bounce, and restrained cinematic contrast.',
			materialDetail:
				'Emphasize seams, edges, roughness shifts, transparent surfaces, and shadow depth without repainting the model into a generic facade.',
			twist:
				'Shadows detach from the geometry as thin black ribbons that point back to the original edges, making the silhouette feel drawn by light.',
			negative:
				'Avoid extra towers, busy crowds, generic neon city clutter, or transformations that alter the building mass.'
		};
	}
	return {
		name: 'Archaeological Broadcast Object',
		type: 'material-culture artifact with impossible signal',
		visualPrinciple:
			'Present the generated geometry as a newly unearthed object transmitting a strange cultural memory, with the exact mesh preserved as the subject.',
		references: [
			'Carlo Scarpa museum display - precise reveal lighting',
			'paper lantern craft - warm handmade translucency',
			'analog video feedback - controlled impossible surface event'
		],
		trendRelevance:
			'The clean object read and single uncanny effect give the image a stronger hook than a neutral studio render.',
		camera:
			'Composed three-quarter hero view, full silhouette readable, named parts separated by light and shadow.',
		colorLight:
			'Neutral material base with warm internal accents, cool rim light, and soft cinematic floor shadows.',
		materialDetail:
			'Preserve material intent while adding tactile surface variation, edge wear, and readable roughness differences.',
		twist:
			'A faint broadcast pattern crawls across the surface as if projected from inside, conforming to the existing geometry instead of replacing it.',
		negative:
			'Avoid changing object count, replacing geometry, decorative clutter, unreadable crops, or effects that hide the form.'
	};
}

function fallbackStoryArc(direction: VisualDirection): NormalizedStoryArc {
	const story = direction.story_for_image_and_3s_animation ?? {};
	const primary = direction.primary_direction ?? {};
	return {
		logline: cleanDirectionText(story.story_beat) || cleanDirectionText(primary.scene_description),
		setup:
			cleanDirectionText(direction.shot_plan?.story_arc?.setup) ||
			cleanDirectionText(primary.scene_description) ||
			'The protagonist geometry is established in its initial quiet state.',
		turn:
			cleanDirectionText(direction.shot_plan?.story_arc?.turn) ||
			cleanDirectionText(story.geometry_action) ||
			cleanDirectionText(story.story_beat) ||
			'The geometry begins its surprising transformation.',
		payoff:
			cleanDirectionText(direction.shot_plan?.story_arc?.payoff) ||
			cleanDirectionText(story.still_image_prompt_addition) ||
			cleanDirectionText(story.geometry_action) ||
			'The transformation resolves into a strong final image.',
		final_state:
			cleanDirectionText(direction.shot_plan?.story_arc?.final_state) ||
			cleanDirectionText(story.still_image_prompt_addition) ||
			'The protagonist geometry holds the transformed final state.'
	};
}

function fallbackFramePrompt(
	direction: VisualDirection,
	frameIndex: number,
	frame: { purpose?: string; framing?: string; view?: string } | undefined
): string {
	const primary = direction.primary_direction ?? {};
	const story = direction.story_for_image_and_3s_animation ?? {};
	const geometry = direction.geometry_read ?? {};
	const arc = fallbackStoryArc(direction);
	const base = compactSentences([
		cleanDirectionText(primary.prompt_ready_direction),
		cleanDirectionText(primary.scene_description),
		cleanDirectionText(primary.camera_and_composition),
		cleanDirectionText(primary.color_and_light),
		cleanDirectionText(primary.material_and_detail)
	]);
	const protagonist = compactSentences([
		cleanDirectionText(geometry.main_character)
			? `Protagonist geometry: ${cleanDirectionText(geometry.main_character)}.`
			: '',
		cleanDirectionText(geometry.dominant_geometry)
	]);
	const frameStates = [
		compactSentences([
			'Story setup still frame:',
			arc.setup,
			'The geometry is intact and readable before the transformation.'
		]),
		compactSentences([
			'Surprising turn still frame:',
			arc.turn,
			cleanDirectionText(story.atmosphere_action),
			cleanDirectionText(story.foreground_action)
		]),
		compactSentences([
			'Payoff still frame:',
			arc.payoff,
			arc.final_state,
			cleanDirectionText(story.still_image_prompt_addition)
		])
	];
	const camera = compactSentences([
		cleanDirectionText(frame?.view) ? `View: ${cleanDirectionText(frame?.view)}.` : '',
		cleanDirectionText(frame?.framing) ? `Framing: ${cleanDirectionText(frame?.framing)}.` : '',
		cleanDirectionText(frame?.purpose) ? `Purpose: ${cleanDirectionText(frame?.purpose)}.` : ''
	]);
	const negative = cleanDirectionText(primary.negative_direction);
	return compactSentences([
		base,
		protagonist,
		frameStates[frameIndex] ?? frameStates[0],
		camera,
		negative ? `Avoid: ${negative}.` : '',
		'Still image only; freeze this exact storyboard beat, preserve the existing scene geometry, silhouette, object count, proportions, and spatial relationships.'
	]);
}

function fallbackPairPrompt(direction: VisualDirection, index: number): string {
	const story = direction.story_for_image_and_3s_animation ?? {};
	const arc = fallbackStoryArc(direction);
	if (index === 0) {
		return compactSentences([
			`Start from the setup state: ${arc.setup}.`,
			`Move into the turn: ${arc.turn}.`,
			cleanDirectionText(story.geometry_action),
			cleanDirectionText(story.atmosphere_action),
			cleanDirectionText(story.camera_move_3s)
		]);
	}
	return compactSentences([
		`Start from the middle turn state: ${arc.turn}.`,
		`Resolve into the payoff: ${arc.payoff}.`,
		arc.final_state,
		cleanDirectionText(story.foreground_action),
		cleanDirectionText(story.loop_potential)
	]);
}

function normalizeShotPlan(direction: VisualDirection): void {
	const existing = direction.shot_plan ?? {};
	const existingFrames = Array.isArray(existing.frames) ? existing.frames.slice(0, 3) : [];
	const defaultFrames: NonNullable<NonNullable<VisualDirection['shot_plan']>['frames']> = [
		{
			label: 'Story setup',
			purpose: 'Establish the geometry, visual direction, and initial state',
			view: 'low_front_3q',
			camera_direction: [-1, 0.55, -1],
			focus_objects: [],
			framing: 'full object with breathing room'
		},
		{
			label: 'Surprising turn',
			purpose: 'Show the first readable transformation while staying connected to the setup',
			view: 'side_detail',
			camera_direction: [1, 0.35, -0.75],
			focus_objects: [],
			framing: 'closer view, still readable as the same object'
		},
		{
			label: 'Payoff frame',
			purpose: 'Resolve the story into the strongest final image',
			view: 'high_back_3q',
			camera_direction: [-0.45, 1.1, 0.65],
			focus_objects: [],
			framing: 'final reveal silhouette'
		}
	];
	const frames = defaultFrames.map((fallback, index) => {
		const frame = { ...fallback, ...(existingFrames[index] ?? {}) };
		const stillPrompt = cleanDirectionText(frame.still_prompt);
		return {
			...frame,
			still_prompt: stillPrompt || fallbackFramePrompt(direction, index, frame)
		};
	});
	const existingPairs = Array.isArray(existing.pair_prompts)
		? existing.pair_prompts.slice(0, 2)
		: [];
	const pair_prompts = [0, 1].map((index) => ({
		...(existingPairs[index] ?? {}),
		from: index,
		to: index + 1,
		role: index === 0 ? ('setup_to_turn' as const) : ('turn_to_payoff' as const),
		prompt: cleanDirectionText(existingPairs[index]?.prompt) || fallbackPairPrompt(direction, index)
	}));
	const fallbackArc = fallbackStoryArc(direction);
	const existingArc = existing.story_arc ?? {};
	direction.shot_plan = {
		...existing,
		aspect_ratio: cleanDirectionText(existing.aspect_ratio) || '16:9',
		story_arc: {
			logline: cleanDirectionText(existingArc.logline) || fallbackArc.logline,
			setup: cleanDirectionText(existingArc.setup) || fallbackArc.setup,
			turn: cleanDirectionText(existingArc.turn) || fallbackArc.turn,
			payoff: cleanDirectionText(existingArc.payoff) || fallbackArc.payoff,
			final_state: cleanDirectionText(existingArc.final_state) || fallbackArc.final_state
		},
		frames,
		pair_prompts
	};
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
	if (Array.isArray(direction.shot_plan?.pair_prompts)) {
		direction.shot_plan = {
			...direction.shot_plan,
			pair_prompts: direction.shot_plan.pair_prompts.slice(0, 2).map((pair, index) => ({
				...pair,
				from: index,
				to: index + 1,
				role: index === 0 ? 'setup_to_turn' : 'turn_to_payoff'
			}))
		};
	}
	normalizeShotPlan(direction);
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

function fallbackDirectionFromContext(options: {
	sceneSummary: string;
	sceneMetadata: string;
	currentPrompt?: string;
	currentDirectionJson?: string;
}): VisualDirection {
	if (options.currentDirectionJson?.trim()) {
		try {
			return normalizeDirection(parseStructuredJson<VisualDirection>(options.currentDirectionJson));
		} catch {
			// Fall back to the scene-derived direction below.
		}
	}

	const draft = cleanDirectionText(options.currentPrompt);
	const summary = cleanDirectionText(options.sceneSummary);
	const metadataHint = cleanDirectionText(options.sceneMetadata).slice(0, 800);
	const recipe = chooseCreativeFallbackRecipe(`${draft}\n${summary}\n${metadataHint}`);
	const sceneDescription = compactSentences([
		'Scene source truth:',
		summary,
		metadataHint ? `Metadata cues: ${metadataHint}` : ''
	]);
	const direction: VisualDirection = {
		geometry_read: {
			dominant_geometry: summary || 'Generated scene geometry from the current Live OBJ.',
			geometry_personality: recipe.visualPrinciple,
			main_character: 'The exact generated geometry and named parts'
		},
		primary_direction: {
			name: recipe.name,
			type: recipe.type,
			why_this_is_the_right_direction:
				'The model returned malformed JSON, so this fallback adds a real art-direction layer while preserving the scene geometry as source truth.',
			visual_principle: recipe.visualPrinciple,
			supporting_references: recipe.references,
			trend_relevance: recipe.trendRelevance,
			camera_and_composition: recipe.camera,
			color_and_light: recipe.colorLight,
			material_and_detail: recipe.materialDetail,
			scene_description: sceneDescription,
			negative_direction: recipe.negative,
			prompt_ready_direction: compactSentences([
				`${recipe.name}: ${recipe.visualPrinciple}`,
				`References: ${recipe.references.join('; ')}.`,
				recipe.camera,
				recipe.colorLight,
				recipe.materialDetail,
				`Unexpected preserved-geometry effect: ${recipe.twist}`,
				'Preserve the exact scene geometry, object count, proportions, named parts, and spatial relationships; use the scene summary only as geometry constraints, not as the creative voice.'
			])
		},
		story_for_image_and_3s_animation: {
			story_title: recipe.name,
			story_beat: `The preserved object begins as a clear design artifact, then ${recipe.twist.toLowerCase()}, ending as a readable hero image with the same parts and silhouette.`,
			emotional_beat: 'Recognition first, then a small uncanny jolt.',
			camera_move_3s:
				'Slow controlled push-in with a slight orbit that keeps the full form legible while the impossible surface event becomes visible.',
			geometry_action: `The geometry remains preserved; ${recipe.twist}`,
			atmosphere_action:
				'Light and reflections react to the impossible material effect while keeping the silhouette clean and inspectable.',
			foreground_action:
				'Small reflections or scale cues move gently, never becoming more important than the object.',
			loop_potential:
				'Good. The impossible effect can fade back into the original neutral material state.',
			animation_prompt: compactSentences([
				`Start from the preserved geometry in the ${recipe.name} direction.`,
				'The camera slowly pushes in as the exact named parts remain fixed and readable.',
				`Then ${recipe.twist.toLowerCase()}`,
				'The effect resolves into a clean final hero view without changing the object count, replacing the model, or hiding the silhouette.'
			]),
			still_image_prompt_addition: compactSentences([
				'clear hero still, readable silhouette, detailed material surfaces, soft shadows, strong but restrained cinematic lighting.',
				`Freeze the twist visibly in the image: ${recipe.twist}`
			])
		},
		reel_copy: {
			story_mode: 'reference_recipe',
			title: recipe.name,
			opening_label: 'Project reveal',
			opening_line: 'The generated form gets a cultural visual rule.',
			concept: recipe.visualPrinciple.slice(0, 90),
			references_title: 'Visual recipe',
			reference_line: 'References guide the mood without replacing the mesh.',
			references: recipe.references,
			process_title: 'Agent build',
			process_steps: [
				'Read the generated scene',
				'Preserved the geometry',
				'Chose one art direction',
				'Mapped references to material',
				'Added one impossible effect',
				'Prepared the hero reveal'
			],
			structure_title: 'Generated scene',
			ending_label: 'Final output',
			ending: 'The object stays intact, but the image has a point of view.'
		}
	};
	return normalizeDirection(direction);
}

async function repairVisualDirectionJson(options: {
	rawContent: string;
	parseError: unknown;
	model: string;
	reqApiKey?: string;
	reqApiUrl?: string;
}): Promise<VisualDirection | null> {
	const parseMessage =
		options.parseError instanceof Error ? options.parseError.message : String(options.parseError);
	const repairPrompt = `Repair this malformed JSON into valid JSON matching the visual direction schema.

Rules:
- Return JSON only.
- Preserve the creative content as much as possible.
- Escape quotes and newlines inside string values.
- Do not add Markdown fences.
- If a field is incomplete, close it with a sensible short phrase.

Parse error:
${parseMessage}

Malformed JSON:
${options.rawContent}`;

	try {
		const repairResult = await withLlmRequestOverrides(
			options.reqApiKey || options.reqApiUrl || options.model
				? { apiKey: options.reqApiKey, apiUrl: options.reqApiUrl, model: options.model }
				: undefined,
			() =>
				requestChatCompletion({
					messages: [
						{
							role: 'system',
							content:
								'You repair malformed JSON. Return only valid JSON and never explain your changes.'
						},
						{ role: 'user', content: repairPrompt }
					],
					model: options.model,
					label: 'api-render-prompt-json-repair',
					temperature: 0,
					maxTokens: 4000
				})
		);
		return normalizeDirection(parseStructuredJson<VisualDirection>(repairResult.content));
	} catch (error) {
		console.warn('[render-prompt] JSON repair failed', {
			error: error instanceof Error ? error.message : String(error)
		});
		return null;
	}
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
When the timeline has three frames, treat the final output as two finite video clips that join into one short story:
- Clip 1 (frame 0 to frame 1) is the opening plot: establish the initial condition, introduce the visual rule, and trigger the irreversible change.
- Clip 2 (frame 1 to frame 2) is the finish: carry the same change forward, reveal its consequence, and land on a clear final state.
The second clip must not restart the idea, swap to an unrelated spectacle, or merely intensify the camera. It must pay off the first clip.
Good animation beats include: facades blooming into signs, columns liquefying because the structure is waking up, cars melting into chrome streams that reveal a path, windows becoming eyes that trigger the lighting change, architecture swallowing the sun and snapping into night, roofs turning into birds or butterflies that reveal the silhouette, furniture inflating into a usable object, shadows becoming characters that guide scale, material switching states as a clear before/after, or a day-to-night snap with a motivated reveal.
Required surprise rule: animation_prompt and both pair_prompts must include at least one concrete non-camera transformation, deformation, impossible material change, or reality-bending event that creates a memorable "wait, what just happened?" moment. Practical motion alone, such as panels sliding, lights turning on, camera orbiting, fog drifting, or rain starting, is not enough unless it triggers a more unexpected visual event.
For restrained architectural directions, keep the surprise elegant but unmistakable: concrete can briefly become paper-thin lantern skin, privacy screens can unfold like ribs, shadows can pull the facade open, wet asphalt can rise into a mirror plane, or light can physically carve/deform the building surface.
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
    "story_arc": {
      "logline": "",
      "setup": "",
      "turn": "",
      "payoff": "",
      "final_state": ""
    },
    "frames": [
      {
        "label": "Story setup",
        "purpose": "Establish the geometry, visual direction, and the question the viewer will follow",
        "view": "low_front_3q",
        "camera_direction": [-1, 0.55, -1],
        "focus_objects": [],
        "framing": "full object with breathing room",
        "still_prompt": ""
      },
      {
        "label": "Surprising turn",
        "purpose": "Show the first readable change, deformation, or reveal while staying connected to the setup",
        "view": "side_detail",
        "camera_direction": [1, 0.35, -0.75],
        "focus_objects": [],
        "framing": "closer view, still readable as the same object",
        "still_prompt": ""
      },
      {
        "label": "Payoff frame",
        "purpose": "Resolve the visual story into the strongest final image",
        "view": "high_back_3q",
        "camera_direction": [-0.45, 1.1, 0.65],
        "focus_objects": [],
        "framing": "final reveal silhouette",
        "still_prompt": ""
      }
    ],
    "pair_prompts": [
      { "from": 0, "to": 1, "role": "setup_to_turn", "prompt": "" },
      { "from": 1, "to": 2, "role": "turn_to_payoff", "prompt": "" }
    ]
  }
}

Rules:
- Output only one primary direction.
- The primary direction must be specific, not generic.
- primary_direction.prompt_ready_direction must read like an art director's creative direction, not a scene inventory or metadata summary.
- It must include one named visual lineage, 2-3 relevant cultural/art/design/cinema/material references, and one concrete unexpected visual effect or twist that is visible in a still image.
- The unexpected still-image effect must preserve the exact geometry; use material state, light behavior, projection, reflection, shadow, condensation, surface patina, or impossible interior glow instead of adding/removing parts.
- Do not paste the object summary, bbox values, vertex counts, metadata tags, source names, or parameter controls into prompt_ready_direction. Those belong only in geometry_read or scene_description as constraints.
- If the Live OBJ scene is sparse or technical, make the creative direction stronger, not more literal.
- If the user provides draft guidance, treat it as creative intent to expand, clarify, and art-direct.
- Preserve concrete user constraints from draft guidance unless they conflict with the Live OBJ geometry.
- If the user provides no draft guidance, choose the strongest direction from the scene metadata alone.
- Supporting references are required and must be limited to 3 maximum. Each reference must explain what it contributes, such as form, material, light, motion, culture, or mood.
- The story must be readable in the still image and expandable into a coherent 3-frame / 3-second sequence.
- The animation must have a clear arc: setup, surprising turn, payoff. It can include unexpected visuals, deformations, material shifts, or impossible events, but they must form one continuous story.
- shot_plan.story_arc must define the finite storyline in plain visual terms: setup, turn, payoff, and final_state. Do not write abstract theme words; describe what the viewer actually sees.
- The animation_prompt must describe the complete visual arc, not just camera movement and not just an isolated transformation.
- The animation_prompt and pair_prompts must make the unexpected transformation explicit. If an existing visual direction is provided and its motion is too practical or calm, preserve the art direction but upgrade the story_for_image_and_3s_animation and shot_plan.pair_prompts with a clearer wow/deformation beat.
- The shot_plan must contain exactly 3 frames designed for this specific geometry and visual direction.
- The shot_plan frames are a storyboard for the final image/video output. Frame 0 sets context, frame 1 changes the situation, and frame 2 pays it off.
- Each shot_plan frame must include still_prompt: a complete image-generation prompt for that exact still frame. It must share the same primary direction, protagonist geometry, color/light/material rules, and camera intent, but describe the exact frozen story state for only that frame.
- still_prompt is for still image generation, not video. It should describe what is visible in the final image at that beat: setup, turn, or payoff. Do not describe multi-second motion inside still_prompt except as visible consequences already frozen in the frame.
- still_prompt must preserve the geometry as the protagonist and must not contradict prompt_ready_direction. It may repeat the most important global style constraints so it can stand alone if edited by the user.
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
- pair_prompts are for two generated videos that will be stitched together. The first prompt is the opening plot, and the second prompt is the finish. They must share the same protagonist, visual rule, transformation logic, atmosphere, and camera continuity.
- The first pair prompt should introduce the motivating change and end on the middle frame as a readable cliffhanger or turn.
- The second pair prompt should begin from that middle-frame state, complete the same transformation, and end with a resolved final image. It should not introduce a new unrelated event.
- Each pair prompt must mention its exact start state and end state, using the selected frame cameras when camera context exists.
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

Choose one strong visual direction and return the required JSON object. If existing visual direction JSON is provided, preserve its core visual direction but update motion/story fields whenever they lack a concrete unexpected transformation or need to align with timeline camera context. When timeline camera context is available, treat the selected timeline frames as a storyboard: align shot_plan frames and pair_prompts to those exact frame cameras, preserve visual continuity between frames, and make the two motion prompts read as setup-to-turn and turn-to-payoff instead of unrelated camera moves.`;

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
		let direction: VisualDirection;
		let parseWarning: string | undefined;
		try {
			direction = normalizeDirection(parseStructuredJson<VisualDirection>(llmResult.content));
		} catch (parseError) {
			parseWarning =
				parseError instanceof Error ? parseError.message : `Invalid JSON: ${String(parseError)}`;
			const repaired = await repairVisualDirectionJson({
				rawContent: llmResult.content,
				parseError,
				model,
				reqApiKey,
				reqApiUrl
			});
			direction =
				repaired ??
				fallbackDirectionFromContext({
					sceneSummary,
					sceneMetadata,
					currentPrompt,
					currentDirectionJson
				});
		}
		let prompt: string;
		try {
			prompt = buildRenderPrompt(direction);
		} catch (buildError) {
			const buildWarning =
				buildError instanceof Error
					? buildError.message
					: `Invalid direction: ${String(buildError)}`;
			parseWarning = parseWarning ? `${parseWarning}; ${buildWarning}` : buildWarning;
			direction = fallbackDirectionFromContext({
				sceneSummary,
				sceneMetadata,
				currentPrompt,
				currentDirectionJson
			});
			prompt = buildRenderPrompt(direction);
		}
		return json({
			prompt,
			direction,
			rawLlm: llmResult.content,
			...(parseWarning ? { parseWarning } : {}),
			...(llmResult.usage ? { llmUsage: llmResult.usage } : {})
		});
	} catch (e) {
		const message = e instanceof Error ? e.message : String(e);
		throw error(502, `Render prompt generation failed: ${message}`);
	}
};
