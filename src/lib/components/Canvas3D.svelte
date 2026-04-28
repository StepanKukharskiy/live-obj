<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import * as THREE from 'three';
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
	export let backgroundColor = '#f0f0f0';
	export let backgroundImageUrl = '';
	export let transparentBackground = false;
	export let showGrid = true;
	export let showAxes = true;
	export let ambientLightIntensity = 1.0;
	export let directionalLightIntensity = 1.5;
	export let showWireframe = false;
	/** Applied to the loaded `renderObject` mesh materials only (not grid/axes). */
	export let objectColor = '#7185d4';
	export let respectObjectMaterials = false;
	export let enableShadows = false;
	export let fogEnabled = false;
	export let fogNear = 10;
	export let fogFar = 50;
	export let fogColor = '#f8fafc';
	export let cameraFov = 50;
	export let cameraProjection: 'perspective' | 'orthographic' = 'perspective';
	export let toneMappingExposure = 1;
	export let renderMode: 'standard' | 'outline' | 'overlay' | 'toon' = 'standard';
	export let outlineColor = '#000000';
	export let outlineBackgroundColor = '#ffffff';
	export let outlineThickness = 1;
	export let outlineDepthSensitivity = 1;
	export let outlineNormalSensitivity = 1;
	export let toonSteps: 2 | 3 | 4 | 5 = 3;
	export let toonOutline = true;
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

	type ScreenshotOptions = {
		maxWidth?: number;
		format?: 'image/png' | 'image/jpeg';
		quality?: number;
		maxBytes?: number;
	};

	const estimateDataUrlBytes = (dataUrl: string): number => {
		const base64Payload = dataUrl.split(',')[1] ?? '';
		return Math.floor((base64Payload.length * 3) / 4);
	};

	export function captureScreenshot(options: ScreenshotOptions = {}) {
		if (!renderer || !scene || !camera) return '';
		const { maxWidth, format = 'image/png', quality: requestedQuality = 0.9, maxBytes } = options;
		renderFrame();

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
				mesh.castShadow = enableShadows;
				mesh.receiveShadow = enableShadows;
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

		// Tone mapping exposure
		if (renderer) {
			renderer.toneMappingExposure = toneMappingExposure;
			renderer.setClearAlpha(transparentBackground ? 0 : 1);
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
			if (objects?.cube) objects.cube.visible = false;
			const bounds = new THREE.Box3().setFromObject(mountedRenderObject);
			if (!bounds.isEmpty() && framedRenderObject !== renderObject) {
				const center = bounds.getCenter(new THREE.Vector3());
				const size = bounds.getSize(new THREE.Vector3());
				const distance = Math.max(size.x, size.y, size.z, 1) * 2.4;
				camera.position.set(center.x + distance, center.y + distance * 0.7, center.z + distance);
				camera.lookAt(center);
				if (camera.isOrthographicCamera) {
					camera.zoom = Math.max(
						0.1,
						ORTHOGRAPHIC_FRUSTUM_HEIGHT / Math.max(size.x, size.y, size.z, 1) / 2.2
					);
					camera.updateProjectionMatrix();
				}
				controls?.target.copy(center);
				controls?.update();
				framedRenderObject = renderObject;
			}
		} else if (objects?.cube) {
			objects.cube.visible = true;
			framedRenderObject = null;
		}

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
		edges.render(scene, camera, {
			edgeColor: outlineColor,
			thickness: outlineThickness,
			depthBias: outlineDepthSensitivity,
			normalBias: outlineNormalSensitivity
		});
	}

	function renderFrame() {
		if (!renderer || !scene || !camera) return;
		if (renderMode === 'standard') {
			renderer.render(scene, camera);
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
		renderer.render(scene, camera);
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
		ortho.position.set(5, 5, 5);
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
		toonMaterialCache.forEach((m) => m.dispose());
		toonMaterialCache.clear();
		toonGradientCache.forEach((t) => t.dispose());
		toonGradientCache.clear();
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

		// Rotate the default cube for demonstration
		if (objects?.cube) {
			objects.cube.rotation.x += 0.01;
			objects.cube.rotation.y += 0.01;
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
