// @ts-nocheck
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export function createScene() {
	return new THREE.Scene();
}

export function createCamera(width, height) {
	const cam = new THREE.PerspectiveCamera(50, width / Math.max(height, 1), 0.1, 2000);
	cam.position.set(-5, 5, -5);
	cam.lookAt(0, 0, 0);
	return cam;
}

export function createRenderer(canvas) {
	const r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
	r.setPixelRatio(Math.min(typeof window !== 'undefined' ? window.devicePixelRatio : 1, 2));
	/* false = do not set canvas CSS width/height so fluid CSS (100%) keeps sizing with the window */
	r.setSize(canvas.clientWidth, canvas.clientHeight, false);
	r.outputColorSpace = THREE.SRGBColorSpace;
	r.shadowMap.type = THREE.PCFSoftShadowMap;
	return r;
}

export function setupLighting(scene) {
	const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
	const directionalLight = new THREE.DirectionalLight(0xffffff, 1.5);
	directionalLight.position.set(-5, 10, -7);
	directionalLight.castShadow = true;
	directionalLight.shadow.mapSize.width = 2048;
	directionalLight.shadow.mapSize.height = 2048;
	directionalLight.shadow.camera.near = 0.5;
	directionalLight.shadow.camera.far = 60;
	directionalLight.shadow.camera.left = -12;
	directionalLight.shadow.camera.right = 12;
	directionalLight.shadow.camera.top = 12;
	directionalLight.shadow.camera.bottom = -12;
	directionalLight.shadow.bias = -0.0005;
	scene.add(ambientLight, directionalLight);
	return { ambientLight, directionalLight };
}

export function createDefaultObjects(scene) {
	const gridHelper = new THREE.GridHelper(20, 20, 0x888888, 0xcccccc);
	const axesHelper = new THREE.AxesHelper(2);
	const groundPlane = new THREE.Mesh(
		new THREE.PlaneGeometry(20, 20),
		new THREE.ShadowMaterial({ color: 0x000000, opacity: 0.16 })
	);
	groundPlane.rotation.x = -Math.PI / 2;
	groundPlane.position.y = -0.002;
	groundPlane.receiveShadow = true;
	groundPlane.name = 'shadow_ground_plane';
	scene.add(groundPlane, gridHelper, axesHelper);
	return { gridHelper, axesHelper, groundPlane };
}

export function setupControls(camera, renderer) {
	const controls = new OrbitControls(camera, renderer.domElement);
	controls.enableDamping = true;
	return controls;
}
