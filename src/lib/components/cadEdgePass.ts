import * as THREE from 'three';

/**
 * Screen-space CAD edge renderer.
 *
 * Renders view-space normals + linearized depth into an offscreen MRT-less target
 * (color = normals, depthTexture = scene depth) using a `MeshNormalMaterial` override,
 * then composites a Sobel-style edge detection pass on top of the current framebuffer.
 *
 * Produces: silhouettes (including curved surfaces like cylinders/spheres), crease edges,
 * and mesh-mesh intersection lines — all from the screen-space depth + normal buffers.
 *
 * Usage:
 *   const edges = new CadEdgeRenderer(renderer);
 *   edges.setSize(w, h);
 *   // standard scene render already done on main framebuffer...
 *   edges.render(scene, camera, { edgeColor: '#000', thickness: 1, depthBias: 1, normalBias: 1 });
 */
export interface CadEdgeOptions {
	edgeColor: string | THREE.Color;
	/** Pixel offset for Sobel taps. 1 = 1px neighborhood. Higher = thicker lines. */
	thickness?: number;
	/** Multiplier on depth-edge sensitivity. Higher = more edges from depth discontinuities. */
	depthBias?: number;
	/** Multiplier on normal-edge sensitivity. Higher = more edges from normal discontinuities. */
	normalBias?: number;
}

const edgeVertexShader = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

const edgeFragmentShader = /* glsl */ `
precision highp float;

uniform sampler2D tNormal;
uniform sampler2D tDepth;
uniform vec2 uResolution;
uniform vec2 uTexel;
uniform float uNear;
uniform float uFar;
uniform vec3 uEdgeColor;
uniform float uThickness;
uniform float uDepthBias;
uniform float uNormalBias;
uniform int uIsPerspective;

varying vec2 vUv;

// Convert non-linear depth buffer value to linear view-space Z distance.
float readLinearDepth(vec2 uv) {
  float d = texture2D(tDepth, uv).x;
  if (uIsPerspective == 1) {
    // viewZ = near*far / (far - d*(far-near))
    float z = (uNear * uFar) / (uFar - d * (uFar - uNear));
    return z;
  }
  // Orthographic: depth maps linearly to [near, far]
  return uNear + d * (uFar - uNear);
}

vec3 readNormal(vec2 uv) {
  // MeshNormalMaterial packs view-space normal into RGB as n*0.5+0.5
  vec3 n = texture2D(tNormal, uv).xyz;
  return normalize(n * 2.0 - 1.0);
}

void main() {
  vec2 o = uTexel * max(uThickness, 0.5);

  // 4 orthogonal taps (Roberts-cross style is enough and cheap; works for thin lines)
  vec2 uvL = vUv - vec2(o.x, 0.0);
  vec2 uvR = vUv + vec2(o.x, 0.0);
  vec2 uvU = vUv + vec2(0.0, o.y);
  vec2 uvD = vUv - vec2(0.0, o.y);

  float dC = readLinearDepth(vUv);
  float dL = readLinearDepth(uvL);
  float dR = readLinearDepth(uvR);
  float dU = readLinearDepth(uvU);
  float dD = readLinearDepth(uvD);

  // Scale depth differences by distance so near edges are not over-emphasized
  float depthScale = max(dC, 0.001);
  float depthDiff = max(
    max(abs(dC - dL), abs(dC - dR)),
    max(abs(dC - dU), abs(dC - dD))
  ) / depthScale;

  vec3 nC = readNormal(vUv);
  vec3 nL = readNormal(uvL);
  vec3 nR = readNormal(uvR);
  vec3 nU = readNormal(uvU);
  vec3 nD = readNormal(uvD);

  float normalDiff = max(
    max(1.0 - dot(nC, nL), 1.0 - dot(nC, nR)),
    max(1.0 - dot(nC, nU), 1.0 - dot(nC, nD))
  );

  // Thresholds tuned so defaults (bias=1) produce clean lines.
  float depthEdge = smoothstep(0.0015, 0.006, depthDiff * uDepthBias);
  float normalEdge = smoothstep(0.15, 0.45, normalDiff * uNormalBias);

  // Background pixels have normal==0 which reads as normalize(-1) = garbage.
  // Detect "no geometry" by checking raw texel length (before normalize).
  vec3 rawN = texture2D(tNormal, vUv).xyz;
  float hasGeom = step(0.05, length(rawN));

  // Also mask edges where neighbor is background but center is background too.
  vec3 rawL = texture2D(tNormal, uvL).xyz;
  vec3 rawR = texture2D(tNormal, uvR).xyz;
  vec3 rawU = texture2D(tNormal, uvU).xyz;
  vec3 rawD = texture2D(tNormal, uvD).xyz;
  float hasAnyGeom = max(
    hasGeom,
    max(
      max(step(0.05, length(rawL)), step(0.05, length(rawR))),
      max(step(0.05, length(rawU)), step(0.05, length(rawD)))
    )
  );

  float edge = max(depthEdge, normalEdge) * hasAnyGeom;

  if (edge < 0.01) discard;
  gl_FragColor = vec4(uEdgeColor, edge);
}
`;

export class CadEdgeRenderer {
	private renderer: THREE.WebGLRenderer;
	private width = 1;
	private height = 1;

	private normalTarget: THREE.WebGLRenderTarget;
	private normalMaterial: THREE.MeshNormalMaterial;

	private quadScene: THREE.Scene;
	private quadCamera: THREE.OrthographicCamera;
	private quadMaterial: THREE.ShaderMaterial;
	private quadMesh: THREE.Mesh;

	constructor(renderer: THREE.WebGLRenderer) {
		this.renderer = renderer;

		const depthTex = new THREE.DepthTexture(1, 1);
		depthTex.type = THREE.UnsignedIntType;
		depthTex.format = THREE.DepthFormat;

		this.normalTarget = new THREE.WebGLRenderTarget(1, 1, {
			minFilter: THREE.NearestFilter,
			magFilter: THREE.NearestFilter,
			format: THREE.RGBAFormat,
			type: THREE.UnsignedByteType,
			depthBuffer: true,
			stencilBuffer: false,
			depthTexture: depthTex
		});

		this.normalMaterial = new THREE.MeshNormalMaterial();
		// MeshNormalMaterial writes view-space normals. We don't want flat shading overrides.
		this.normalMaterial.side = THREE.DoubleSide;

		this.quadCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
		this.quadScene = new THREE.Scene();

		this.quadMaterial = new THREE.ShaderMaterial({
			vertexShader: edgeVertexShader,
			fragmentShader: edgeFragmentShader,
			transparent: true,
			depthTest: false,
			depthWrite: false,
			uniforms: {
				tNormal: { value: this.normalTarget.texture },
				tDepth: { value: this.normalTarget.depthTexture },
				uResolution: { value: new THREE.Vector2(1, 1) },
				uTexel: { value: new THREE.Vector2(1, 1) },
				uNear: { value: 0.1 },
				uFar: { value: 1000 },
				uEdgeColor: { value: new THREE.Color(0, 0, 0) },
				uThickness: { value: 1 },
				uDepthBias: { value: 1 },
				uNormalBias: { value: 1 },
				uIsPerspective: { value: 1 }
			}
		});

		const quadGeom = new THREE.PlaneGeometry(2, 2);
		this.quadMesh = new THREE.Mesh(quadGeom, this.quadMaterial);
		this.quadMesh.frustumCulled = false;
		this.quadScene.add(this.quadMesh);
	}

	setSize(width: number, height: number) {
		const pr = this.renderer.getPixelRatio();
		const w = Math.max(1, Math.floor(width * pr));
		const h = Math.max(1, Math.floor(height * pr));
		if (w === this.width && h === this.height) return;
		this.width = w;
		this.height = h;
		this.normalTarget.setSize(w, h);
		const u = this.quadMaterial.uniforms;
		u.uResolution.value.set(w, h);
		u.uTexel.value.set(1 / w, 1 / h);
	}

	/**
	 * Renders edges on top of the current framebuffer (does NOT clear).
	 * Leaves renderer autoClear state unchanged for caller.
	 */
	render(scene: THREE.Scene, camera: THREE.Camera, options: CadEdgeOptions) {
		// 1) Render view-space normals + depth into normalTarget
		const prevOverride = scene.overrideMaterial;
		const prevBackground = scene.background;
		const prevTarget = this.renderer.getRenderTarget();
		const prevAutoClear = this.renderer.autoClear;
		const prevClearColor = this.renderer.getClearColor(new THREE.Color()).clone();
		const prevClearAlpha = this.renderer.getClearAlpha();

		scene.overrideMaterial = this.normalMaterial;
		scene.background = null;
		this.renderer.autoClear = true;
		this.renderer.setClearColor(0x000000, 0);
		this.renderer.setRenderTarget(this.normalTarget);
		this.renderer.clear(true, true, false);
		this.renderer.render(scene, camera);

		// Restore scene state
		scene.overrideMaterial = prevOverride;
		scene.background = prevBackground;
		this.renderer.setRenderTarget(prevTarget);
		this.renderer.setClearColor(prevClearColor, prevClearAlpha);
		this.renderer.autoClear = prevAutoClear;

		// 2) Configure edge shader uniforms
		const u = this.quadMaterial.uniforms;
		const cam = camera as THREE.PerspectiveCamera & THREE.OrthographicCamera;
		u.uNear.value = cam.near ?? 0.1;
		u.uFar.value = cam.far ?? 1000;
		u.uIsPerspective.value = (camera as THREE.PerspectiveCamera).isPerspectiveCamera ? 1 : 0;
		u.uEdgeColor.value = new THREE.Color(options.edgeColor);
		u.uThickness.value = Math.max(0.5, options.thickness ?? 1);
		u.uDepthBias.value = Math.max(0, options.depthBias ?? 1);
		u.uNormalBias.value = Math.max(0, options.normalBias ?? 1);

		// 3) Composite edges on top of current framebuffer (no clear)
		const prevAutoClear2 = this.renderer.autoClear;
		this.renderer.autoClear = false;
		this.renderer.render(this.quadScene, this.quadCamera);
		this.renderer.autoClear = prevAutoClear2;
	}

	dispose() {
		this.normalTarget.dispose();
		this.normalTarget.depthTexture?.dispose?.();
		this.normalMaterial.dispose();
		this.quadMaterial.dispose();
		(this.quadMesh.geometry as THREE.BufferGeometry).dispose();
	}
}
