import {
  ACESFilmicToneMapping,
  Box3,
  DirectionalLight,
  Group,
  HemisphereLight,
  type Material,
  Mesh,
  OrthographicCamera,
  PCFSoftShadowMap,
  PMREMGenerator,
  Scene,
  Texture,
  Vector3,
  WebGLRenderer,
} from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import paladinUrl from '../assets/library-tome/paladin-tome.glb?url';

/** Loaded only for the empty Library. CSS supplies the float; WebGL renders on demand. */
export async function mountLibraryTome(
  canvas: HTMLCanvasElement,
  signal: AbortSignal,
  onReady: (ready: boolean) => void,
): Promise<() => void> {
  const renderer = new WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = PCFSoftShadowMap;
  const scene = new Scene();
  const camera = new OrthographicCamera(-1.8, 1.8, 1.3, -1.3, 0.1, 30);
  camera.position.set(0, 6, 8);
  camera.lookAt(0, 0, 0);
  const book = new Group();
  scene.add(book);
  const environment = new RoomEnvironment();
  const pmrem = new PMREMGenerator(renderer);
  const environmentMap = pmrem.fromScene(environment);
  scene.environment = environmentMap.texture;
  scene.environmentIntensity = 0.65;
  environment.dispose();
  pmrem.dispose();
  scene.add(new HemisphereLight(0xffefd7, 0x3c2430, 1.3));
  const key = new DirectionalLight(0xffe4bf, 2.4);
  key.position.set(-3, 5, 6);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.left = -3;
  key.shadow.camera.right = 3;
  key.shadow.camera.top = 3;
  key.shadow.camera.bottom = -3;
  key.shadow.normalBias = 0.015;
  scene.add(key);
  const fill = new DirectionalLight(0xc6d5f5, 0.8);
  fill.position.set(4, 1, -2);
  scene.add(fill);

  let observer: ResizeObserver | undefined;
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    observer?.disconnect();
    canvas.removeEventListener('webglcontextlost', contextLost);
    canvas.removeEventListener('webglcontextrestored', render);
    const textures = new Set<Texture>();
    const materials = new Set<Material>();
    scene.traverse((object) => {
      if (!(object instanceof Mesh)) return;
      object.geometry.dispose();
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        materials.add(material);
        for (const value of Object.values(material)) {
          if (value instanceof Texture) textures.add(value);
        }
      }
    });
    for (const texture of textures) {
      const image = texture.source.data;
      if (typeof ImageBitmap !== 'undefined' && image instanceof ImageBitmap) image.close();
      texture.dispose();
    }
    for (const material of materials) material.dispose();
    key.shadow.dispose();
    environmentMap.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
  };
  function render() {
    if (disposed || signal.aborted || renderer.getContext().isContextLost()) return;
    const { clientWidth: width, clientHeight: height } = canvas;
    if (!width || !height) return;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height, false);
    const halfHeight = 1.3;
    camera.left = -halfHeight * (width / height);
    camera.right = halfHeight * (width / height);
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
    onReady(true);
  }
  function contextLost(event: Event) {
    event.preventDefault();
    onReady(false);
  }

  try {
    const response = await fetch(paladinUrl, { signal });
    if (!response.ok) throw new Error(`Could not load Library tome: ${response.status}`);
    const gltf = await new GLTFLoader().parseAsync(await response.arrayBuffer(), '');
    book.add(gltf.scene);
    if (signal.aborted) {
      dispose();
      return dispose;
    }
    gltf.scene.traverse((object) => {
      if (object instanceof Mesh) {
        object.castShadow = true;
        object.receiveShadow = true;
      }
    });

    // Lay the pages back so the open spine faces the viewer and the leaves fan upward.
    gltf.scene.rotation.set(-1.05, Math.PI - 0.12, 0);
    gltf.scene.updateMatrixWorld(true);
    const bounds = new Box3().setFromObject(gltf.scene);
    const size = bounds.getSize(new Vector3());
    const center = bounds.getCenter(new Vector3());
    const scale = 3.15 / Math.max(size.x, size.y * 1.35);
    gltf.scene.scale.multiplyScalar(scale);
    gltf.scene.position.sub(center.multiplyScalar(scale));
    canvas.addEventListener('webglcontextlost', contextLost);
    canvas.addEventListener('webglcontextrestored', render);
    observer = new ResizeObserver(render);
    observer.observe(canvas);
    render();
    return dispose;
  } catch (error) {
    dispose();
    throw error;
  }
}
