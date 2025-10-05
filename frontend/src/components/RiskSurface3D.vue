<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

const props = defineProps({
  surfaceData: {
    type: Object,
    required: true,
  },
});

const mountPoint = ref(null);
let renderer, scene, camera, controls;
let animationFrameId;

function init() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x111827);

  camera = new THREE.PerspectiveCamera(75, mountPoint.value.clientWidth / mountPoint.value.clientHeight, 0.1, 1000);
  camera.position.set(0, 70, 100);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(mountPoint.value.clientWidth, mountPoint.value.clientHeight);
  mountPoint.value.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(ambientLight);
  const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
  directionalLight.position.set(1, 1, 1);
  scene.add(directionalLight);

  const axesHelper = new THREE.AxesHelper(50);
  scene.add(axesHelper);

  createSurface();
  animate();
}

function createSurface() {
  const { price_axis, time_axis, pnl_surface } = props.surfaceData;
  const width = price_axis.length - 1;
  const height = time_axis.length - 1;

  const geometry = new THREE.PlaneGeometry(150, 150, width, height);
  const colors = [];
  
  let maxPnl = -Infinity;
  let minPnl = Infinity;
  pnl_surface.flat().forEach(pnl => {
    if (pnl > maxPnl) maxPnl = pnl;
    if (pnl < minPnl) minPnl = pnl;
  });
  
  const pnlRange = maxPnl - minPnl;
  const zScale = pnlRange > 0 ? 50 / pnlRange : 0;

  const positions = geometry.attributes.position;
  const numVertices = positions.count;

  for (let i = 0; i < numVertices; i++) {
    const yIndex = Math.floor(i / (width + 1));
    const xIndex = i % (width + 1);
    
    if (pnl_surface[yIndex] && pnl_surface[yIndex][xIndex] !== undefined) {
      const pnl = pnl_surface[yIndex][xIndex];
      positions.setZ(i, -pnl * zScale);

      const color = new THREE.Color();
      if (pnl > 0) {
        color.setHSL(0.33, 1.0, 0.5); // Green
      } else {
        color.setHSL(0.0, 1.0, 0.5); // Red
      }
      colors.push(color.r, color.g, color.b);
    }
  }

  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  
  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    side: THREE.DoubleSide,
    wireframe: true, // <-- THIS IS THE CHANGE
  });

  const mesh = new THREE.Mesh(geometry, material);
  mesh.rotation.x = -Math.PI / 2;
  scene.add(mesh);
}

function animate() {
  animationFrameId = requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}

function cleanup() {
  if (animationFrameId) cancelAnimationFrame(animationFrameId);
  if (renderer) renderer.dispose();
  if (controls) controls.dispose();
  if (mountPoint.value && renderer?.domElement) {
    mountPoint.value.removeChild(renderer.domElement);
  }
}

onMounted(() => {
  if (props.surfaceData) {
    init();
  }
});

onUnmounted(() => {
  cleanup();
});

const handleResize = () => {
    if(camera && renderer && mountPoint.value){
        camera.aspect = mountPoint.value.clientWidth / mountPoint.value.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(mountPoint.value.clientWidth, mountPoint.value.clientHeight);
    }
};
window.addEventListener('resize', handleResize);
onUnmounted(() => window.removeEventListener('resize', handleResize));

</script>

<template>
  <div ref="mountPoint" class="w-full h-[600px]"></div>
</template>