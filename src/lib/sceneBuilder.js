// @ts-nocheck
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export function createScene() {
	return new THREE.Scene();
}

export function createCamera(width, height) {
	const cam = new THREE.PerspectiveCamera(50, width / Math.max(height, 1), 0.1, 2000);
	cam.position.set(5, 5, 5);
	cam.lookAt(0, 0, 0);
	return cam;
}

export function createRenderer(canvas) {
	const r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
	r.setPixelRatio(Math.min(typeof window !== 'undefined' ? window.devicePixelRatio : 1, 2));
	r.setSize(canvas.clientWidth, canvas.clientHeight);
	r.outputColorSpace = THREE.SRGBColorSpace;
	return r;
}

export function setupLighting(scene) {
	const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
	const directionalLight = new THREE.DirectionalLight(0xffffff, 1.5);
	directionalLight.position.set(5, 10, 7);
	scene.add(ambientLight, directionalLight);
	return { ambientLight, directionalLight };
}

export function createDefaultObjects(scene) {
	const gridHelper = new THREE.GridHelper(20, 20, 0x888888, 0xcccccc);
	const axesHelper = new THREE.AxesHelper(2);
	const geo = new THREE.BoxGeometry(1, 1, 1);
	const mat = new THREE.MeshStandardMaterial({ color: 0x4488ff });
	const cube = new THREE.Mesh(geo, mat);
	scene.add(gridHelper, axesHelper, cube);
	return { gridHelper, axesHelper, cube };
}

export function setupControls(camera, renderer) {
	const controls = new OrbitControls(camera, renderer.domElement);
	controls.enableDamping = true;
	return controls;
}
