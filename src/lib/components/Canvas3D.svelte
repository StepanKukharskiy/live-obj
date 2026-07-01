<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import * as THREE from 'three';
	import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
	import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js';
	import { OBJExporter } from 'three/examples/jsm/exporters/OBJExporter.js';
	import { CadEdgeRenderer } from './cadEdgePass';
	import {
		createScene,
		createCamera,
		createRenderer,
		setupLighting,
		createDefaultObjects,
		setupControls
	} from '$lib/sceneBuilder.js';

	export let className = '';
	export let renderObject: any = null;
	export let backgroundColor = '#3a3a36';
	export let backgroundImageUrl = '';
	export let transparentBackground = false;
	export let showGrid = false;
	export let showAxes = false;
	export let ambientLightIntensity = 1.0;
	export let directionalLightIntensity = 1.5;
	export let showWireframe = false;
	/** Applied to the loaded `renderObject` mesh materials only (not grid/axes). */
	export let objectColor = '#e6e4dd';
	export let respectObjectMaterials = false;
	export let enableShadows = true;
	export let fogEnabled = false;
	export let fogNear = 10;
	export let fogFar = 50;
	export let fogColor = '#f8fafc';
	export let cameraFov = 50;
	export let cameraProjection: 'perspective' | 'orthographic' = 'perspective';
	export let autoFrameOnObjectChange = false;
	export let suppressAutoFrame = false;
	export let toneMappingExposure = 1;
	export let renderMode: 'standard' | 'outline' | 'overlay' | 'toon' = 'standard';
	export let outlineColor = '#000000';
	export let outlineBackgroundColor = '#ffffff';
	export let outlineThickness = 1;
	export let outlineDepthSensitivity = 1;
	export let outlineNormalSensitivity = 1;
	export let toonSteps: 2 | 3 | 4 | 5 = 3;
	export let toonOutline = true;
	export let editorTransformMode: 'select' | 'translate' | 'rotate' | 'scale' = 'select';
	export let selectedObjectName = '';
	export let selectedObjectTransform:
		| {
				position: [number, number, number];
				rotation: [number, number, number];
				scale: [number, number, number];
				pivot: [number, number, number];
		  }
		| null = null;
	export let onSelectObject: ((objectName: string) => void) | undefined = undefined;
	export let onTransformCommit:
		| ((update: {
				objectName: string;
				position: [number, number, number];
				rotation: [number, number, number];
				scale: [number, number, number];
				pivot: [number, number, number];
		  }) => void | Promise<void>)
		| undefined = undefined;
	// Deprecated props kept for backward-compat with demo2; currently unused.
	export let outlineThresholdAngle: number | undefined = undefined;
	export let outlineStylePreset: string | undefined = undefined;
	void outlineThresholdAngle;
	void outlineStylePreset;

	let canvas: HTMLCanvasElement;
	let scene: any;
	let camera: any;
	let renderer: any;
	let animationId: number;
	let lights: any;
	let objects: any;
	let controls: any;
	let mountedRenderObject: any = null;
	let framedRenderObject: any = null;
	let containerWidth = 800;
	let containerHeight = 600;
	let canvasShell: HTMLDivElement | undefined;
	let cadEdges: CadEdgeRenderer | null = null;
	let transformControls: TransformControls | null = null;
	let transformHelper: THREE.Object3D | null = null;
	let editorPivot: THREE.Object3D | null = null;
	let selectionBox: THREE.BoxHelper | null = null;
	let selectedTransformObject: THREE.Object3D | null = null;
	let transformDragging = false;
	let transformDragStart:
		| {
				pivotPosition: THREE.Vector3;
				transform: {
					position: [number, number, number];
					rotation: [number, number, number];
					scale: [number, number, number];
					pivot: [number, number, number];
				};
		  }
		| null = null;
	let suppressNextCanvasClick = false;
	let loadedBackgroundImage: HTMLImageElement | null = null;
	let loadedBackgroundImageUrl = '';
	let animationPaused = false; // Pause animation during cleanup
	let lastFrameTime = 0;
	let targetFPS = 60;
	let frameInterval = 1000 / targetFPS;
	let sceneControlsTimeout: any = null;
	const ORTHOGRAPHIC_FRUSTUM_HEIGHT = 10;
	const outlineFillMaterial = new THREE.MeshBasicMaterial({
		color: '#ffffff',
		side: THREE.DoubleSide
	});
	const selectionBoxColor = new THREE.Color('#0000eb');
	const transformRaycaster = new THREE.Raycaster();
	const transformPointer = new THREE.Vector2();

	function markEditorHelper(object: THREE.Object3D | null) {
		if (!object) return;
		object.userData.editorHelper = true;
		object.traverse((child) => {
			child.userData.editorHelper = true;
		});
	}

	function isEditorHelper(object: any): boolean {
		let current = object;
		while (current) {
			if (current.userData?.editorHelper) return true;
			current = current.parent;
		}
		return false;
	}

	function isShadowGroundPlane(object: any) {
		return object === objects?.groundPlane || object?.name === 'shadow_ground_plane';
	}

	function withShadowGroundHidden<T>(renderFn: () => T): T {
		const groundPlane = objects?.groundPlane;
		if (!groundPlane) return renderFn();
		const wasVisible = groundPlane.visible;
		groundPlane.visible = false;
		try {
			return renderFn();
		} finally {
			groundPlane.visible = wasVisible;
		}
	}

	// ---- Toon (anime cel-shading) support ----
	const toonGradientCache = new Map<number, THREE.DataTexture>();
	function getToonGradientMap(steps: number): THREE.DataTexture {
		const n = Math.max(2, Math.min(5, Math.floor(steps)));
		const cached = toonGradientCache.get(n);
		if (cached) return cached;
		const data = new Uint8Array(n);
		for (let i = 0; i < n; i++) {
			data[i] = Math.round((i / (n - 1)) * 255);
		}
		const tex = new THREE.DataTexture(data, n, 1, THREE.RedFormat, THREE.UnsignedByteType);
		tex.magFilter = THREE.NearestFilter;
		tex.minFilter = THREE.NearestFilter;
		tex.generateMipmaps = false;
		tex.needsUpdate = true;
		toonGradientCache.set(n, tex);
		return tex;
	}

	// Cache toon material keyed by (originalMaterial uuid + steps) so per-mesh color/map is preserved.
	const toonMaterialCache = new Map<string, THREE.MeshToonMaterial>();
	function getToonMaterialFor(src: THREE.Material, steps: number): THREE.MeshToonMaterial {
		const key = `${src.uuid}::${steps}`;
		const cached = toonMaterialCache.get(key);
		if (cached) {
			cached.gradientMap = getToonGradientMap(steps);
			return cached;
		}
		const anySrc = src as any;
		const toon = new THREE.MeshToonMaterial({
			color: anySrc.color ? anySrc.color.clone() : new THREE.Color(0xffffff),
			map: anySrc.map ?? null,
			alphaMap: anySrc.alphaMap ?? null,
			transparent: Boolean(anySrc.transparent),
			opacity: anySrc.opacity ?? 1,
			side: anySrc.side ?? THREE.FrontSide,
			gradientMap: getToonGradientMap(steps)
		});
		// If the original material is using vertex colors (e.g. merged group preview), honor it.
		if (anySrc.vertexColors) toon.vertexColors = true;
		toonMaterialCache.set(key, toon);
		return toon;
	}

	function withToonMaterials<T>(renderFn: () => T): T {
		if (!scene) return renderFn();
		const swapped: Array<{ mesh: any; original: any }> = [];
		scene.traverse((child: any) => {
			if (isShadowGroundPlane(child) || isEditorHelper(child)) return;
			if (!child?.isMesh || !child.material || child.visible === false) return;
			const original = child.material;
			if (Array.isArray(original)) {
				const toonArr = original.map((m: THREE.Material) => getToonMaterialFor(m, toonSteps));
				swapped.push({ mesh: child, original });
				child.material = toonArr;
			} else {
				swapped.push({ mesh: child, original });
				child.material = getToonMaterialFor(original, toonSteps);
			}
		});
		try {
			return renderFn();
		} finally {
			for (const { mesh, original } of swapped) {
				mesh.material = original;
			}
		}
	}

	type DepthStandardMaterial = THREE.MeshStandardMaterial & {
		userData: {
			depthShaderUniforms?: {
				uDepthMix: { value: number };
				uShapeMix: { value: number };
				uDepthNear: { value: number };
				uDepthFar: { value: number };
			};
		};
	};

	const depthNormalShaderCache = new Map<string, DepthStandardMaterial>();

	function clamp01(value: unknown, fallback: number): number {
		const n = typeof value === 'number' && Number.isFinite(value) ? value : fallback;
		return Math.max(0, Math.min(1, n));
	}

	function getDepthNormalShaderMaterialFor(
		src: THREE.Material,
		depthNear: number,
		depthFar: number
	): DepthStandardMaterial {
		const key = src.uuid;
		const cached = depthNormalShaderCache.get(key);
		const anySrc = src as any;
		const color = anySrc.color ? anySrc.color.clone() : new THREE.Color(objectColor || '#e6e4dd');
		const roughness = clamp01(anySrc.roughness, 0.82);
		const metalness = clamp01(anySrc.metalness, 0);
		const opacity = anySrc.opacity ?? 1;
		if (cached) {
			cached.color.copy(color);
			cached.roughness = roughness;
			cached.metalness = metalness;
			cached.opacity = opacity;
			cached.transparent = Boolean(anySrc.transparent) || opacity < 1;
			cached.side = anySrc.side ?? THREE.FrontSide;
			cached.flatShading = Boolean(anySrc.flatShading);
			cached.vertexColors = Boolean(anySrc.vertexColors);
			cached.map = anySrc.map ?? null;
			cached.alphaMap = anySrc.alphaMap ?? null;
			cached.userData.depthShaderUniforms!.uDepthNear.value = depthNear;
			cached.userData.depthShaderUniforms!.uDepthFar.value = depthFar;
			cached.wireframe = Boolean(anySrc.wireframe);
			return cached;
		}
		const uniforms = {
			uDepthMix: { value: 0.34 },
			uShapeMix: { value: 0.38 },
			uDepthNear: { value: depthNear },
			uDepthFar: { value: depthFar }
		};
		const shader = new THREE.MeshStandardMaterial({
			color,
			roughness,
			metalness,
			side: anySrc.side ?? THREE.FrontSide,
			flatShading: Boolean(anySrc.flatShading),
			vertexColors: Boolean(anySrc.vertexColors),
			map: anySrc.map ?? null,
			alphaMap: anySrc.alphaMap ?? null,
			transparent: Boolean(anySrc.transparent) || opacity < 1,
			opacity,
			wireframe: Boolean(anySrc.wireframe)
		}) as DepthStandardMaterial;
		shader.userData.depthShaderUniforms = uniforms;
		shader.onBeforeCompile = (compiledShader) => {
			compiledShader.uniforms.uDepthMix = uniforms.uDepthMix;
			compiledShader.uniforms.uShapeMix = uniforms.uShapeMix;
			compiledShader.uniforms.uDepthNear = uniforms.uDepthNear;
			compiledShader.uniforms.uDepthFar = uniforms.uDepthFar;
			compiledShader.fragmentShader = `
				uniform float uDepthMix;
				uniform float uShapeMix;
				uniform float uDepthNear;
				uniform float uDepthFar;
				${compiledShader.fragmentShader}
			`.replace(
				'#include <normal_fragment_maps>',
				`
				#include <normal_fragment_maps>
				float spellshapeDepth = smoothstep(uDepthNear, uDepthFar, -vViewPosition.z);
				vec3 spellshapeNormal = normalize(normal);
				vec3 spellshapeViewDir = normalize(-vViewPosition);
				float spellshapeRimBase = 1.0 - max(dot(spellshapeNormal, spellshapeViewDir), 0.0);
				float spellshapeFresnel = spellshapeRimBase * spellshapeRimBase;
				float spellshapeDepthShade = mix(1.06, 0.80, spellshapeDepth);
				float spellshapeShapeShade = 0.94 + spellshapeFresnel * 0.34;
				float spellshapeShade = mix(1.0, spellshapeShapeShade, uShapeMix);
				spellshapeShade *= mix(1.0, spellshapeDepthShade, uDepthMix);
				diffuseColor.rgb *= clamp(spellshapeShade, 0.82, 1.2);
				`
			);
		};
		shader.customProgramCacheKey = () =>
			`spellshape-depth-standard-v3-${shader.flatShading ? 'flat' : 'smooth'}`;
		depthNormalShaderCache.set(key, shader);
		return shader;
	}

	function withDepthNormalShaderMaterials<T>(renderFn: () => T): T {
		if (!scene || !camera) return renderFn();
		const swapped: Array<{ mesh: any; original: any }> = [];
		const bounds = mountedRenderObject ? new THREE.Box3().setFromObject(mountedRenderObject) : null;
		const size =
			bounds && !bounds.isEmpty()
				? bounds.getSize(new THREE.Vector3())
				: new THREE.Vector3(1, 1, 1);
		const span = Math.max(size.x, size.y, size.z, 1);
		const depthNear = Math.max(0.01, camera.near ?? 0.1);
		const depthFar = Math.max(
			depthNear + 0.01,
			Math.min(camera.far ?? 2000, depthNear + span * 3.5)
		);
		scene.traverse((child: any) => {
			if (isShadowGroundPlane(child) || isEditorHelper(child)) return;
			if (!child?.isMesh || !child.material || child.visible === false) return;
			const original = child.material;
			if (Array.isArray(original)) {
				swapped.push({ mesh: child, original });
				child.material = original.map((m: THREE.Material) =>
					getDepthNormalShaderMaterialFor(m, depthNear, depthFar)
				);
			} else {
				swapped.push({ mesh: child, original });
				child.material = getDepthNormalShaderMaterialFor(original, depthNear, depthFar);
			}
		});
		try {
			return renderFn();
		} finally {
			for (const { mesh, original } of swapped) {
				mesh.material = original;
			}
		}
	}

	function makeXrayMaterial(color: string, opacity: number, depthWrite: boolean) {
		return new THREE.MeshBasicMaterial({
			color,
			transparent: opacity < 1,
			opacity,
			depthWrite,
			depthTest: true,
			side: THREE.DoubleSide
		});
	}

	function withXrayMaterials<T>(
		focusObjectNames: string[] | undefined,
		supportObjectNames: string[] | undefined,
		renderFn: () => T
	): T {
		if (!scene) return renderFn();
		const focusSet = new Set((focusObjectNames ?? []).map((name) => name.trim()).filter(Boolean));
		if (focusSet.size === 0) return renderFn();
		const supportSet = new Set(
			(supportObjectNames ?? []).map((name) => name.trim()).filter(Boolean)
		);
		const focusMaterial = makeXrayMaterial('#7dd3fc', 1, true);
		focusMaterial.wireframe = true;
		const supportMaterial = makeXrayMaterial('#fbbf24', 0.55, false);
		const contextMaterial = makeXrayMaterial('#7f8792', 0.16, false);
		const swapped: Array<{ mesh: any; original: any }> = [];
		scene.traverse((child: any) => {
			if (isShadowGroundPlane(child) || isEditorHelper(child)) return;
			if (!child?.isMesh || !child.material || child.visible === false) return;
			swapped.push({ mesh: child, original: child.material });
			if (focusSet.has(child.name)) {
				child.material = focusMaterial;
			} else if (supportSet.has(child.name)) {
				child.material = supportMaterial;
			} else {
				child.material = contextMaterial;
			}
		});
		try {
			return renderFn();
		} finally {
			for (const { mesh, original } of swapped) {
				mesh.material = original;
			}
			focusMaterial.dispose();
			supportMaterial.dispose();
			contextMaterial.dispose();
		}
	}

	type ScreenshotOptions = {
		maxWidth?: number;
		format?: 'image/png' | 'image/jpeg';
		quality?: number;
		maxBytes?: number;
		autoFrame?: boolean;
		framePadding?: number;
		viewDirection?: [number, number, number];
		focusObjectNames?: string[];
		xrayFocusObjectNames?: string[];
		xraySupportObjectNames?: string[];
	};

	const estimateDataUrlBytes = (dataUrl: string): number => {
		const base64Payload = dataUrl.split(',')[1] ?? '';
		return Math.floor((base64Payload.length * 3) / 4);
	};

	function normalizedViewDirection(viewDirection?: [number, number, number]) {
		const fallback = new THREE.Vector3(-1, 0.65, -1);
		if (!viewDirection) return fallback.normalize();
		const next = new THREE.Vector3(viewDirection[0], viewDirection[1], viewDirection[2]);
		if (next.lengthSq() < 1e-6) return fallback.normalize();
		return next.normalize();
	}

	function boundsForFocusObjects(focusObjectNames?: string[]): THREE.Box3 | null {
		if (!mountedRenderObject || !focusObjectNames?.length) return null;
		const focusSet = new Set(focusObjectNames.map((name) => name.trim()).filter(Boolean));
		if (focusSet.size === 0) return null;
		const bounds = new THREE.Box3();
		let matched = false;
		mountedRenderObject.traverse((object: any) => {
			if (!object?.isMesh || !object.name || !focusSet.has(object.name)) return;
			const objectBounds = new THREE.Box3().setFromObject(object);
			if (objectBounds.isEmpty()) return;
			bounds.union(objectBounds);
			matched = true;
		});
		return matched ? bounds : null;
	}

	function selectableObjectName(object: THREE.Object3D | null): string {
		let current = object;
		while (current && current !== mountedRenderObject) {
			if (current.name && !isEditorHelper(current)) return current.name;
			current = current.parent;
		}
		return '';
	}

	function findSelectedObject(): THREE.Object3D | null {
		if (!mountedRenderObject || !selectedObjectName.trim()) return null;
		let exact: THREE.Object3D | null = null;
		mountedRenderObject.traverse((object: THREE.Object3D) => {
			if (exact || isEditorHelper(object)) return;
			if (object.name === selectedObjectName) exact = object;
		});
		return exact;
	}

	function selectedPivot(object: THREE.Object3D): [number, number, number] {
		const bounds = new THREE.Box3().setFromObject(object);
		if (bounds.isEmpty()) return [0, 0, 0];
		const center = bounds.getCenter(new THREE.Vector3());
		const localCenter = object.worldToLocal(center.clone());
		return [localCenter.x, localCenter.y, localCenter.z];
	}

	function sourceRotationQuaternion(rotation: [number, number, number] | undefined): THREE.Quaternion {
		// raw_obj_post_executor rotates vertices around X, then Y, then Z; Three represents that
		// same matrix with Euler order ZYX for the authored [rx, ry, rz] values.
		return new THREE.Quaternion().setFromEuler(
			new THREE.Euler(
				THREE.MathUtils.degToRad(rotation?.[0] ?? 0),
				THREE.MathUtils.degToRad(rotation?.[1] ?? 0),
				THREE.MathUtils.degToRad(rotation?.[2] ?? 0),
				'ZYX'
			)
		);
	}

	function displayQuaternionFromSourceRotation(
		rotation: [number, number, number] | undefined
	): THREE.Quaternion {
		mountedRenderObject?.updateWorldMatrix(true, true);
		const rootQuaternion = mountedRenderObject
			? mountedRenderObject.getWorldQuaternion(new THREE.Quaternion())
			: new THREE.Quaternion();
		return rootQuaternion.multiply(sourceRotationQuaternion(rotation));
	}

	function sourceRotationFromDisplayQuaternion(quaternion: THREE.Quaternion): [number, number, number] {
		mountedRenderObject?.updateWorldMatrix(true, true);
		const rootQuaternion = mountedRenderObject
			? mountedRenderObject.getWorldQuaternion(new THREE.Quaternion())
			: new THREE.Quaternion();
		const sourceQuaternion = rootQuaternion.invert().multiply(quaternion.clone());
		const sourceEuler = new THREE.Euler().setFromQuaternion(sourceQuaternion, 'ZYX');
		return [
			THREE.MathUtils.radToDeg(sourceEuler.x),
			THREE.MathUtils.radToDeg(sourceEuler.y),
			THREE.MathUtils.radToDeg(sourceEuler.z)
		];
	}

	function updateSelectionHelper() {
		if (!selectionBox || !transformControls || !transformHelper || !editorPivot) return;
		if (transformDragging) {
			if (selectedTransformObject) selectionBox.setFromObject(selectedTransformObject);
			return;
		}
		const target = findSelectedObject();
		selectedTransformObject = target;
		if (!target) {
			selectionBox.visible = false;
			transformControls.detach();
			transformHelper.visible = false;
			return;
		}
		selectionBox.setFromObject(target);
		selectionBox.visible = true;
		target.updateWorldMatrix(true, false);
		mountedRenderObject?.updateWorldMatrix(true, true);
		const bounds = new THREE.Box3().setFromObject(target);
		const center = bounds.isEmpty()
			? target.getWorldPosition(new THREE.Vector3())
			: bounds.getCenter(new THREE.Vector3());
		editorPivot.position.copy(center);
		editorPivot.quaternion.copy(displayQuaternionFromSourceRotation(selectedObjectTransform?.rotation));
		editorPivot.scale.set(1, 1, 1);
		if (editorTransformMode === 'select') {
			transformControls.detach();
			transformHelper.visible = false;
			return;
		}
		transformControls.attach(editorPivot);
		transformControls.setMode(editorTransformMode);
		transformControls.setSpace('local');
		transformHelper.visible = true;
	}

	function commitSelectedTransform() {
		if (!selectedTransformObject || !editorPivot || !selectedObjectName || !onTransformCommit) return;
		const start = transformDragStart;
		const base = start?.transform ?? {
			position: selectedObjectTransform?.position ?? [0, 0, 0],
			rotation: selectedObjectTransform?.rotation ?? [0, 0, 0],
			scale: selectedObjectTransform?.scale ?? [1, 1, 1],
			pivot: selectedObjectTransform?.pivot ?? selectedPivot(selectedTransformObject)
		};
		const startPivot = start?.pivotPosition ?? editorPivot.position;
		const delta = editorPivot.position.clone().sub(startPivot);
		const sourceDelta = mountedRenderObject
			? mountedRenderObject
					.worldToLocal(startPivot.clone().add(delta))
					.sub(mountedRenderObject.worldToLocal(startPivot.clone()))
			: delta;
		void onTransformCommit({
			objectName: selectedObjectName,
			position: [
				base.position[0] + sourceDelta.x,
				base.position[1] + sourceDelta.y,
				base.position[2] + sourceDelta.z
			],
			rotation: sourceRotationFromDisplayQuaternion(editorPivot.quaternion),
			scale:
				editorTransformMode === 'scale'
					? [
							base.scale[0] * editorPivot.scale.x,
							base.scale[1] * editorPivot.scale.y,
							base.scale[2] * editorPivot.scale.z
						]
					: base.scale,
			pivot: base.pivot
		});
		transformDragStart = null;
	}

	function handleCanvasClick(event: MouseEvent) {
		if (!canvas || !camera || !mountedRenderObject || transformDragging) return;
		if (suppressNextCanvasClick) {
			suppressNextCanvasClick = false;
			return;
		}
		const rect = canvas.getBoundingClientRect();
		transformPointer.x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1;
		transformPointer.y = -(((event.clientY - rect.top) / Math.max(rect.height, 1)) * 2 - 1);
		transformRaycaster.setFromCamera(transformPointer, camera);
		const candidates: THREE.Object3D[] = [];
		mountedRenderObject.traverse((object: THREE.Object3D) => {
			if ((object as THREE.Mesh).isMesh && !isEditorHelper(object)) candidates.push(object);
		});
		const hit = transformRaycaster.intersectObjects(candidates, false)[0]?.object ?? null;
		const name = selectableObjectName(hit);
		onSelectObject?.(name);
	}

	function withEditorHelpersHidden<T>(renderFn: () => T): T {
		const helpers = [transformHelper, selectionBox].filter(Boolean) as THREE.Object3D[];
		const states = helpers.map((helper) => ({ helper, visible: helper.visible }));
		for (const helper of helpers) helper.visible = false;
		try {
			return renderFn();
		} finally {
			for (const { helper, visible } of states) helper.visible = visible;
		}
	}

	function frameMountedRenderObject(
		padding = 1.05,
		viewDirectionInput?: [number, number, number],
		focusObjectNames?: string[]
	): boolean {
		if (!mountedRenderObject || !camera || !controls) return false;
		const bounds = boundsForFocusObjects(focusObjectNames) ?? new THREE.Box3().setFromObject(mountedRenderObject);
		if (bounds.isEmpty()) return false;

		const center = bounds.getCenter(new THREE.Vector3());
		const size = bounds.getSize(new THREE.Vector3());
		const sphere = bounds.getBoundingSphere(new THREE.Sphere());
		const radius = Math.max(sphere.radius, Math.max(size.x, size.y, size.z, 1) * 0.5);
		const viewDirection = normalizedViewDirection(viewDirectionInput);

		if (camera.isPerspectiveCamera) {
			const fovRad = THREE.MathUtils.degToRad(camera.fov || cameraFov || 50);
			const distance = (radius / Math.sin(Math.max(0.01, fovRad * 0.5))) * padding;
			camera.position.copy(center).addScaledVector(viewDirection, distance);
			camera.near = Math.max(0.01, distance / 100);
			camera.far = Math.max(2000, distance * 20);
		} else if (camera.isOrthographicCamera) {
			const aspect = Math.max(1e-6, containerWidth / Math.max(containerHeight, 1));
			const fitHeight = Math.max(size.y, size.x / aspect, size.z / aspect, 1) * padding;
			camera.position.copy(center).addScaledVector(viewDirection, Math.max(radius * 3, 5));
			camera.zoom = Math.max(0.1, ORTHOGRAPHIC_FRUSTUM_HEIGHT / fitHeight);
		}

		camera.lookAt(center);
		camera.updateProjectionMatrix();
		controls.target.copy(center);
		controls.update();
		framedRenderObject = renderObject;
		return true;
	}

	export function frameScene(
		padding = 1.05,
		viewDirection?: [number, number, number],
		focusObjectNames?: string[]
	) {
		const framed = frameMountedRenderObject(padding, viewDirection, focusObjectNames);
		if (framed) renderFrame();
		return framed;
	}

	export function captureScreenshot(options: ScreenshotOptions = {}) {
		if (!renderer || !scene || !camera) return '';
		const {
			maxWidth,
			format = 'image/png',
			quality: requestedQuality = 0.9,
			maxBytes,
			autoFrame = false,
			framePadding = 1.05,
			viewDirection,
			focusObjectNames,
			xrayFocusObjectNames,
			xraySupportObjectNames
		} = options;
		if (autoFrame) frameScene(framePadding, viewDirection, focusObjectNames);
		withEditorHelpersHidden(() => {
			if (xrayFocusObjectNames?.length) {
				withXrayMaterials(xrayFocusObjectNames, xraySupportObjectNames, () => {
					renderer.render(scene, camera);
				});
			} else {
				renderFrame();
			}
		});

		const sourceCanvas = document.createElement('canvas');
		sourceCanvas.width = renderer.domElement.width;
		sourceCanvas.height = renderer.domElement.height;
		const sourceContext = sourceCanvas.getContext('2d');
		if (!sourceContext) return renderer.domElement.toDataURL(format, requestedQuality);

		if (!transparentBackground || !backgroundImageUrl) {
			sourceContext.drawImage(renderer.domElement, 0, 0, sourceCanvas.width, sourceCanvas.height);
		} else {
			if (loadedBackgroundImage && loadedBackgroundImageUrl === backgroundImageUrl) {
				sourceContext.drawImage(
					loadedBackgroundImage,
					0,
					0,
					sourceCanvas.width,
					sourceCanvas.height
				);
			}
			sourceContext.drawImage(renderer.domElement, 0, 0, sourceCanvas.width, sourceCanvas.height);
		}
		if (xrayFocusObjectNames?.length) withEditorHelpersHidden(() => renderFrame());

		const initialScale =
			typeof maxWidth === 'number' && maxWidth > 0 && sourceCanvas.width > maxWidth
				? maxWidth / sourceCanvas.width
				: 1;

		let targetWidth = Math.max(1, Math.round(sourceCanvas.width * initialScale));
		let targetHeight = Math.max(1, Math.round(sourceCanvas.height * initialScale));
		let currentQuality = requestedQuality;

		const encodeScreenshot = () => {
			const encodedCanvas = document.createElement('canvas');
			encodedCanvas.width = targetWidth;
			encodedCanvas.height = targetHeight;
			const encodedContext = encodedCanvas.getContext('2d');
			if (!encodedContext) return sourceCanvas.toDataURL(format, currentQuality);
			encodedContext.drawImage(sourceCanvas, 0, 0, targetWidth, targetHeight);
			return encodedCanvas.toDataURL(format, currentQuality);
		};

		let screenshotDataUrl = encodeScreenshot();
		if (typeof maxBytes === 'number' && maxBytes > 0 && format === 'image/jpeg') {
			let attempts = 0;
			while (estimateDataUrlBytes(screenshotDataUrl) > maxBytes && attempts < 7) {
				if (currentQuality > 0.5) {
					currentQuality = Math.max(0.5, currentQuality - 0.1);
				} else {
					targetWidth = Math.max(1, Math.round(targetWidth * 0.85));
					targetHeight = Math.max(1, Math.round(targetHeight * 0.85));
				}
				screenshotDataUrl = encodeScreenshot();
				attempts += 1;
			}
		}

		return screenshotDataUrl;
	}

	export function captureCameraSnapshot() {
		if (!camera || !controls) return null;
		return {
			projection: cameraProjection,
			position: camera.position.toArray(),
			target: controls.target?.toArray?.() ?? [0, 0, 0],
			fov: camera.fov ?? null,
			zoom: camera.zoom ?? null
		};
	}

	export async function exportToGLB(): Promise<Blob> {
		return new Promise((resolve, reject) => {
			if (!scene) return reject(new Error('Scene not initialized'));
			const exporter = new GLTFExporter();
			exporter.parse(
				scene,
				(result) => {
					if (result instanceof ArrayBuffer) {
						resolve(new Blob([result], { type: 'application/octet-stream' }));
					} else {
						const json = JSON.stringify(result);
						resolve(new Blob([json], { type: 'application/octet-stream' }));
					}
				},
				(error) => reject(error),
				{ binary: true }
			);
		});
	}

	export async function exportToOBJ(): Promise<Blob> {
		return new Promise((resolve, reject) => {
			if (!scene) return reject(new Error('Scene not initialized'));
			try {
				const exporter = new OBJExporter();
				const result = exporter.parse(scene);
				resolve(new Blob([result], { type: 'text/plain' }));
			} catch (error) {
				reject(error);
			}
		});
	}

	export function downloadGLB() {
		exportToGLB().then((blob) => {
			const url = URL.createObjectURL(blob);
			const link = document.createElement('a');
			link.href = url;
			link.download = 'scene.glb';
			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
			URL.revokeObjectURL(url);
		});
	}

	export function downloadOBJ() {
		exportToOBJ().then((blob) => {
			const url = URL.createObjectURL(blob);
			const link = document.createElement('a');
			link.href = url;
			link.download = 'scene.obj';
			document.body.appendChild(link);
			link.click();
			document.body.removeChild(link);
			URL.revokeObjectURL(url);
		});
	}

	function updateLoadedBackgroundImage() {
		if (!backgroundImageUrl) {
			loadedBackgroundImage = null;
			loadedBackgroundImageUrl = '';
			return;
		}

		const img = new Image();
		img.onload = () => {
			loadedBackgroundImage = img;
			loadedBackgroundImageUrl = backgroundImageUrl;
		};
		img.onerror = () => {
			console.warn('[Canvas3D] Failed to load background image:', backgroundImageUrl);
			loadedBackgroundImage = null;
			loadedBackgroundImageUrl = '';
		};
		img.src = backgroundImageUrl;
	}

	function applySceneControlsDebounced() {
		if (sceneControlsTimeout) {
			clearTimeout(sceneControlsTimeout);
		}
		sceneControlsTimeout = setTimeout(() => {
			applySceneControls();
			sceneControlsTimeout = null;
		}, 16); // Debounce to ~60fps
	}

	function applyUserMeshColor() {
		if (respectObjectMaterials) return;
		if (!mountedRenderObject || objectColor == null || objectColor === '') return;
		const c = new THREE.Color();
		try {
			c.setStyle(objectColor);
		} catch {
			return;
		}
		mountedRenderObject.traverse((child: any) => {
			if (!child.isMesh || !child.material) return;
			const applyMat = (mat: any) => {
				if (!mat) return;
				// Per-vertex tints (common on OBJ) override uniform material.color until disabled.
				if ('vertexColors' in mat) mat.vertexColors = false;
				if (mat.color) mat.color.copy(c);
			};
			if (Array.isArray(child.material)) {
				for (const mat of child.material) applyMat(mat);
			} else {
				applyMat(child.material);
			}
		});
	}

	function applySceneControls() {
		if (!scene || !objects) return;
		scene.background = transparentBackground ? null : new THREE.Color(backgroundColor);
		if (objects?.gridHelper) objects.gridHelper.visible = showGrid;
		if (objects?.axesHelper) objects.axesHelper.visible = showAxes;
		if (objects?.groundPlane) objects.groundPlane.visible = enableShadows;

		if (lights) {
			if (lights.ambientLight) lights.ambientLight.intensity = ambientLightIntensity;
			if (lights.directionalLight) lights.directionalLight.intensity = directionalLightIntensity;
		}

		// Wireframe: all mesh materials in the scene
		scene.traverse((child: any) => {
			if (child.isMesh && child.material) {
				if (Array.isArray(child.material)) {
					child.material.forEach((mat: any) => {
						if (mat) mat.wireframe = showWireframe;
					});
				} else {
					child.material.wireframe = showWireframe;
				}
			}
		});

		// Mesh albedo: user-loaded object only (keeps in sync with panel; does not recolor grid/helpers)
		applyUserMeshColor();

		// Shadows - batch updates
		if (renderer) {
			renderer.shadowMap.enabled = enableShadows;
			const meshesToUpdate: any[] = [];
			const lightsToUpdate: any[] = [];

			scene.traverse((child: any) => {
				if (child.isMesh) {
					meshesToUpdate.push(child);
				}
				if (child.isLight && child.shadow) {
					lightsToUpdate.push(child);
				}
			});

			meshesToUpdate.forEach((mesh) => {
				const isGroundPlane = mesh === objects?.groundPlane || mesh.name === 'shadow_ground_plane';
				mesh.castShadow = enableShadows && !isGroundPlane;
				mesh.receiveShadow = enableShadows;
				if (isGroundPlane) mesh.visible = enableShadows;
			});

			lightsToUpdate.forEach((light) => {
				light.castShadow = enableShadows;
			});
		}

		// Fog
		if (fogEnabled) {
			scene.fog = new THREE.Fog(new THREE.Color(fogColor), fogNear, fogFar);
		} else {
			scene.fog = null;
		}

		// Camera FOV
		if (camera) {
			if (camera.isPerspectiveCamera) {
				camera.fov = cameraFov;
			}
			camera.updateProjectionMatrix();
		}
	}

	function updateRenderObject() {
		if (!scene) return;

		// Store reference to old object before cleanup
		const oldRenderObject = mountedRenderObject;

		if (oldRenderObject) {
			// Pause animation during cleanup
			animationPaused = true;

			// Remove old object from scene immediately (no traversal needed)
			scene.remove(oldRenderObject);

			// Clear the reference immediately
			mountedRenderObject = null;

			// Resume animation after a short delay to allow cleanup to complete
			setTimeout(() => {
				animationPaused = false;
			}, 50);
		}

		if (renderObject) {
			mountedRenderObject = renderObject;
			scene.add(mountedRenderObject);
			if (
				autoFrameOnObjectChange &&
				!suppressAutoFrame &&
				framedRenderObject !== renderObject &&
				!renderObject.userData?.skipAutoFrame
			) {
				frameMountedRenderObject(1.05);
			}
		}
		updateSelectionHelper();

		// New mesh must pick up current objectColor / wireframe even if those props did not change.
		if (scene && objects) {
			applySceneControls();
		}
	}

	function ensureCadEdges() {
		if (!renderer) return null;
		if (!cadEdges) {
			cadEdges = new CadEdgeRenderer(renderer);
			cadEdges.setSize(containerWidth, containerHeight);
		}
		return cadEdges;
	}

	function renderEdgeLayer() {
		if (!renderer || !scene || !camera) return;
		const edges = ensureCadEdges();
		if (!edges) return;
		withShadowGroundHidden(() => {
			edges.render(scene, camera, {
				edgeColor: outlineColor,
				thickness: outlineThickness,
				depthBias: outlineDepthSensitivity,
				normalBias: outlineNormalSensitivity
			});
		});
	}

	function renderFrame() {
		if (!renderer || !scene || !camera) return;
		if (renderMode === 'standard') {
			withDepthNormalShaderMaterials(() => {
				renderer.render(scene, camera);
			});
			return;
		}
		if (renderMode === 'overlay') {
			renderer.render(scene, camera);
			renderEdgeLayer();
			return;
		}
		if (renderMode === 'toon') {
			withToonMaterials(() => {
				renderer.render(scene, camera);
			});
			if (toonOutline) renderEdgeLayer();
			return;
		}
		// Outline (CAD) mode: flat-color fills using the background color so only
		// the detected edges are visible. Depth is still written by the fill so
		// edges respect occlusion.
		const previousBackground = scene.background;
		const previousOverrideMaterial = scene.overrideMaterial;
		const previousFog = scene.fog;
		const showBackgroundImageInOutline = Boolean(backgroundImageUrl);
		const previousClearAlpha = renderer.getClearAlpha();
		const previousClearColor = renderer.getClearColor(new THREE.Color()).clone();
		const bgColor = new THREE.Color(outlineBackgroundColor);
		outlineFillMaterial.color.copy(bgColor);
		scene.background = showBackgroundImageInOutline ? null : bgColor;
		if (showBackgroundImageInOutline) {
			renderer.setClearColor(previousClearColor, 0);
		}
		scene.overrideMaterial = outlineFillMaterial;
		scene.fog = null;
		withShadowGroundHidden(() => renderer.render(scene, camera));
		scene.overrideMaterial = previousOverrideMaterial;
		scene.fog = previousFog;
		renderEdgeLayer();
		scene.background = previousBackground;
		if (showBackgroundImageInOutline) {
			renderer.setClearColor(previousClearColor, previousClearAlpha);
		}
	}

	function createOrthographicCamera(width: number, height: number) {
		const aspect = Math.max(1e-6, width / Math.max(height, 1));
		const halfHeight = ORTHOGRAPHIC_FRUSTUM_HEIGHT / 2;
		const halfWidth = halfHeight * aspect;
		const ortho = new THREE.OrthographicCamera(
			-halfWidth,
			halfWidth,
			halfHeight,
			-halfHeight,
			0.1,
			2000
		);
		ortho.userData.frustumHeight = ORTHOGRAPHIC_FRUSTUM_HEIGHT;
		ortho.position.set(-5, 5, -5);
		ortho.lookAt(0, 0, 0);
		return ortho;
	}

	function applyCameraResize(width: number, height: number) {
		if (!camera || !renderer) return;
		const safeWidth = Math.max(1, width);
		const safeHeight = Math.max(1, height);
		const aspect = safeWidth / safeHeight;
		if (camera.isOrthographicCamera) {
			const frustumHeight = camera.userData?.frustumHeight ?? ORTHOGRAPHIC_FRUSTUM_HEIGHT;
			const halfHeight = frustumHeight / 2;
			const halfWidth = halfHeight * aspect;
			camera.left = -halfWidth;
			camera.right = halfWidth;
			camera.top = halfHeight;
			camera.bottom = -halfHeight;
		} else if (camera.isPerspectiveCamera) {
			camera.aspect = aspect;
		}
		camera.updateProjectionMatrix();
		/* Third arg false: never pin canvas.style width/height — that breaks resize (clientWidth stays stuck). */
		renderer.setSize(safeWidth, safeHeight, false);
	}

	/** Sync renderer + camera + CAD pass to the canvas CSS size (and DPR). Uses ResizeObserver + resize listeners because window resize alone misses layout-only changes and does not drive Svelte updates. */
	function syncCanvasDimensions() {
		if (!renderer || !canvas) return;
		const rect = canvas.getBoundingClientRect();
		const w = Math.max(1, Math.round(rect.width));
		const h = Math.max(1, Math.round(rect.height));
		containerWidth = w;
		containerHeight = h;
		const pr = Math.min(typeof window !== 'undefined' ? window.devicePixelRatio : 1, 2);
		renderer.setPixelRatio(pr);
		applyCameraResize(w, h);
		cadEdges?.setSize(w, h);
	}

	function updateCameraProjection() {
		if (!camera || !renderer) return;
		const wantsOrtho = cameraProjection === 'orthographic';
		if (wantsOrtho === Boolean(camera.isOrthographicCamera)) return;
		const nextCamera = wantsOrtho
			? createOrthographicCamera(containerWidth, containerHeight)
			: createCamera(containerWidth, containerHeight);
		nextCamera.position.copy(camera.position);
		nextCamera.quaternion.copy(camera.quaternion);
		if (controls) {
			controls.object = nextCamera;
			controls.update();
		}
		camera = nextCamera;
		if (transformControls) transformControls.camera = camera;
		applyCameraResize(containerWidth, containerHeight);
	}

	onMount(() => {
		if (!canvas) return;

		// Initialize water time tracking
		(window as any)._lastWaterTime = performance.now();

		// Set initial dimensions
		containerWidth = canvas.clientWidth;
		containerHeight = canvas.clientHeight;

		// Initialize scene
		scene = createScene();

		// Setup camera
		camera =
			cameraProjection === 'orthographic'
				? createOrthographicCamera(containerWidth, containerHeight)
				: createCamera(containerWidth, containerHeight);

		// Setup renderer (strip stale Three inline px sizes from older builds — those freeze layout size)
		canvas.style.removeProperty('width');
		canvas.style.removeProperty('height');

		// Setup renderer
		renderer = createRenderer(canvas);
		ensureCadEdges();

		// Setup lighting
		lights = setupLighting(scene);

		// Add default objects
		objects = createDefaultObjects(scene);

		// Setup controls
		controls = setupControls(camera, renderer);
		transformControls = new TransformControls(camera, renderer.domElement);
		transformHelper = transformControls.getHelper();
		markEditorHelper(transformHelper);
		transformHelper.visible = false;
		editorPivot = new THREE.Object3D();
		markEditorHelper(editorPivot);
		scene.add(editorPivot);
		transformControls.addEventListener('dragging-changed', (event: any) => {
			transformDragging = Boolean(event.value);
			suppressNextCanvasClick = transformDragging || suppressNextCanvasClick;
			if (controls) controls.enabled = !transformDragging;
			if (transformDragging && editorPivot) {
				transformDragStart = {
					pivotPosition: editorPivot.position.clone(),
					transform: {
						position: selectedObjectTransform?.position ?? [0, 0, 0],
						rotation: selectedObjectTransform?.rotation ?? [0, 0, 0],
						scale: selectedObjectTransform?.scale ?? [1, 1, 1],
						pivot: selectedObjectTransform?.pivot ?? (selectedTransformObject ? selectedPivot(selectedTransformObject) : [0, 0, 0])
					}
				};
			}
			if (!transformDragging) {
				commitSelectedTransform();
			}
		});
		transformControls.addEventListener('objectChange', () => {
			if (selectedTransformObject && selectionBox) selectionBox.setFromObject(selectedTransformObject);
		});
		scene.add(transformHelper);
		selectionBox = new THREE.BoxHelper(new THREE.Object3D(), selectionBoxColor);
		markEditorHelper(selectionBox);
		selectionBox.visible = false;
		scene.add(selectionBox);
		canvas.addEventListener('click', handleCanvasClick);
		applySceneControls();
		updateRenderObject();

		// Start animation loop
		animate(performance.now());

		syncCanvasDimensions();

		const handleWindowResize = () => syncCanvasDimensions();
		window.addEventListener('resize', handleWindowResize);

		const vv = typeof window !== 'undefined' ? window.visualViewport : null;
		if (vv) vv.addEventListener('resize', handleWindowResize);

		let canvasResizeObserver: ResizeObserver | undefined;
		if (canvasShell && typeof ResizeObserver !== 'undefined') {
			canvasResizeObserver = new ResizeObserver(() => syncCanvasDimensions());
			canvasResizeObserver.observe(canvasShell);
		}

		return () => {
			window.removeEventListener('resize', handleWindowResize);
			canvas.removeEventListener('click', handleCanvasClick);
			if (vv) vv.removeEventListener('resize', handleWindowResize);
			canvasResizeObserver?.disconnect();
		};
	});

	onDestroy(() => {
		if (animationId) {
			cancelAnimationFrame(animationId);
		}
		cadEdges?.dispose();
		cadEdges = null;
		transformControls?.dispose();
		transformControls = null;
		transformHelper = null;
		editorPivot = null;
		selectionBox?.geometry.dispose();
		(selectionBox?.material as THREE.Material | undefined)?.dispose?.();
		selectionBox = null;
		toonMaterialCache.forEach((m) => m.dispose());
		toonMaterialCache.clear();
		toonGradientCache.forEach((t) => t.dispose());
		toonGradientCache.clear();
		depthNormalShaderCache.forEach((m) => m.dispose());
		depthNormalShaderCache.clear();
		if (renderer) {
			renderer.dispose();
		}
	});

	function animate(currentTime: number) {
		animationId = requestAnimationFrame(animate);

		// Frame rate limiting
		if (currentTime - lastFrameTime < frameInterval) {
			return;
		}
		lastFrameTime = currentTime;

		// Update controls
		if (controls) {
			controls.update();
		}

		// Update water animations (optimized)
		if (
			!animationPaused &&
			scene &&
			mountedRenderObject &&
			typeof mountedRenderObject.traverse === 'function'
		) {
			const deltaTime = currentTime - (window as any)._lastWaterTime || 0;
			(window as any)._lastWaterTime = currentTime;

			// Skip water updates if too frequent
			if (deltaTime > 16) {
				// ~60fps throttle
				try {
					// Use a more efficient traversal - only check userData once
					const objectsToUpdate: any[] = [];
					mountedRenderObject.traverse((object: any) => {
						if (object?.userData?.updateWater && object?.userData?.waterAnimation) {
							objectsToUpdate.push(object);
						}
					});

					// Update only objects that need water animation
					objectsToUpdate.forEach((object) => {
						try {
							object.userData.updateWater(deltaTime);
							if (object.geometry?.attributes?.position) {
								object.geometry.attributes.position.needsUpdate = true;
							}
						} catch (error) {
							console.warn('[Canvas3D] Water animation error:', error);
							// Disable problematic water animation completely
							object.userData.updateWater = null;
							object.userData.waterAnimation = null;
						}
					});
				} catch (error) {
					console.warn('[Canvas3D] Render object traversal error:', error);
					// Pause animation briefly to prevent continuous errors
					animationPaused = true;
					setTimeout(() => {
						animationPaused = false;
					}, 100);
				}
			}
		}

		renderFrame();
	}

	$: if (renderer && camera && cameraProjection) {
		updateCameraProjection();
	}

	$: if (scene && camera && objects && renderObject !== undefined) {
		updateRenderObject();
	}

	$: if (scene && transformControls) {
		void selectedObjectName;
		void editorTransformMode;
		void selectedObjectTransform;
		updateSelectionHelper();
	}

	$: if (backgroundImageUrl !== loadedBackgroundImageUrl) {
		updateLoadedBackgroundImage();
	}

	// Scene look + wireframe + shadows; debounced. (objectColor handled separately for instant mesh tint.)
	$: if (scene && objects) {
		void backgroundColor;
		void transparentBackground;
		void showGrid;
		void showAxes;
		void ambientLightIntensity;
		void directionalLightIntensity;
		void showWireframe;
		void enableShadows;
		void fogEnabled;
		void fogNear;
		void fogFar;
		void fogColor;
		void cameraFov;
		void toneMappingExposure;
		applySceneControlsDebounced();
	}

	// Immediate mesh tint when color changes (avoids debounce; does not require lights).
	$: if (scene && mountedRenderObject) {
		void objectColor;
		applyUserMeshColor();
	}
</script>

<div
	bind:this={canvasShell}
	class={`canvas-shell ${className}`}
	class:canvas-shell--monochrome-bg={renderMode === 'outline' && !!backgroundImageUrl}
	style:background-image={backgroundImageUrl ? `url(${backgroundImageUrl})` : 'none'}
>
	<canvas bind:this={canvas}></canvas>
</div>

<style>
	.canvas-shell {
		width: 100%;
		height: 100%;
		background-size: cover;
		background-position: center;
		background-repeat: no-repeat;
	}

	.canvas-shell--monochrome-bg {
		filter: grayscale(1) contrast(1.15);
	}

	canvas {
		display: block;
		width: 100%;
		height: 100%;
		pointer-events: auto;
		touch-action: none;
		border-radius: 8px;
		box-shadow:
			0 4px 6px -1px rgba(0, 0, 0, 0.1),
			0 2px 4px -1px rgba(0, 0, 0, 0.06);
	}
</style>
