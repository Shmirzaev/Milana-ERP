"use client";

import { useEffect, useRef } from "react";

type Cleanup = () => void;

export default function FeatureFlowScene() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    let mounted = true;
    let cleanup: Cleanup | undefined;

    async function boot() {
      const THREE = await import("three");
      if (!mounted || !canvasRef.current) return;

      const canvas = canvasRef.current;
      const host = canvas.parentElement || canvas;
      const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
      renderer.setClearColor(0x000000, 0);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
      camera.position.set(0, 2.15, 10.4);

      const root = new THREE.Group();
      root.rotation.x = -0.08;
      scene.add(root);

      const styles = getComputedStyle(document.documentElement);
      const colorVar = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback;
      const ink = new THREE.Color(colorVar("--erp-text", "#14110b"));
      const accent = new THREE.Color(colorVar("--erp-accent", "#c2410c"));
      const success = new THREE.Color(colorVar("--erp-success", "#1f7a4d"));
      const blue = new THREE.Color(colorVar("--erp-blue", "#1e5fb3"));
      const border = new THREE.Color(colorVar("--erp-border-strong", "#ded9ca"));
      const soft = new THREE.Color(colorVar("--erp-border-soft", "#ecebe3"));

      const ambient = new THREE.AmbientLight(0xfff7ea, 1.35);
      scene.add(ambient);

      const key = new THREE.DirectionalLight(0xffffff, 2.2);
      key.position.set(2.5, 5, 4);
      scene.add(key);

      const rim = new THREE.DirectionalLight(0xf08a55, 1.25);
      rim.position.set(-4, 1.5, -2.5);
      scene.add(rim);

      const disposables: Array<{ dispose: () => void }> = [];

      const grid = new THREE.GridHelper(13, 13, border, soft);
      grid.position.set(0, -1.72, -0.15);
      grid.material.opacity = 0.42;
      grid.material.transparent = true;
      root.add(grid);

      const curves = [
        new THREE.CatmullRomCurve3([
          new THREE.Vector3(-5.2, -0.75, 0.1),
          new THREE.Vector3(-3.7, 0.55, -0.55),
          new THREE.Vector3(-2.2, 0.28, 0.62),
          new THREE.Vector3(-0.6, 1.05, -0.28),
          new THREE.Vector3(0.8, 0.58, 0.5),
          new THREE.Vector3(2.45, 1.18, -0.36),
          new THREE.Vector3(4.8, 0.08, 0.18),
        ]),
        new THREE.CatmullRomCurve3([
          new THREE.Vector3(-4.8, 0.45, -0.48),
          new THREE.Vector3(-3.25, 1.02, 0.38),
          new THREE.Vector3(-1.45, 0.15, -0.68),
          new THREE.Vector3(0.15, 0.8, 0.72),
          new THREE.Vector3(1.8, 0.05, -0.45),
          new THREE.Vector3(4.65, 0.72, 0.32),
        ]),
        new THREE.CatmullRomCurve3([
          new THREE.Vector3(-4.95, -1.22, -0.2),
          new THREE.Vector3(-2.8, -0.55, 0.55),
          new THREE.Vector3(-1.1, -1.05, -0.54),
          new THREE.Vector3(0.65, -0.32, 0.46),
          new THREE.Vector3(2.35, -0.85, -0.18),
          new THREE.Vector3(4.55, -0.42, 0.2),
        ]),
      ];

      const curveColors = [accent, success, ink];
      curves.forEach((curve, index) => {
        const geometry = new THREE.TubeGeometry(curve, 92, index === 0 ? 0.032 : 0.024, 10, false);
        const material = new THREE.MeshStandardMaterial({
          color: curveColors[index],
          roughness: 0.48,
          metalness: 0.08,
          transparent: true,
          opacity: index === 0 ? 0.9 : 0.68,
        });
        const mesh = new THREE.Mesh(geometry, material);
        root.add(mesh);
        disposables.push(geometry, material);
      });

      const stationGeometry = new THREE.BoxGeometry(0.42, 0.42, 0.42);
      const stationMaterial = new THREE.MeshStandardMaterial({
        color: colorVar("--erp-surface", "#fdfcf8"),
        roughness: 0.4,
        metalness: 0.08,
      });
      const stationEdgeGeometry = new THREE.EdgesGeometry(stationGeometry);
      const stationEdgeMaterial = new THREE.LineBasicMaterial({ color: ink, transparent: true, opacity: 0.34 });
      disposables.push(stationGeometry, stationMaterial, stationEdgeGeometry, stationEdgeMaterial);

      const stationPositions = [
        [-4.7, -0.7, 0.12],
        [-3.5, 0.76, -0.42],
        [-2.2, 0.08, 0.52],
        [-0.7, 0.96, -0.18],
        [0.75, 0.48, 0.42],
        [2.1, 1.08, -0.28],
        [3.55, 0.42, 0.08],
        [4.72, -0.04, 0.18],
      ];

      stationPositions.forEach(([x, y, z], index) => {
        const group = new THREE.Group();
        group.position.set(x, y, z);
        group.rotation.set(0.42, index * 0.44, 0.08);
        const cube = new THREE.Mesh(stationGeometry, stationMaterial);
        const edges = new THREE.LineSegments(stationEdgeGeometry, stationEdgeMaterial);
        group.add(cube, edges);
        root.add(group);
      });

      const packetGeometry = new THREE.BoxGeometry(0.34, 0.24, 0.22);
      const packetMaterials = [
        new THREE.MeshStandardMaterial({ color: accent, roughness: 0.34, metalness: 0.15 }),
        new THREE.MeshStandardMaterial({ color: success, roughness: 0.38, metalness: 0.12 }),
        new THREE.MeshStandardMaterial({ color: blue, roughness: 0.38, metalness: 0.1 }),
      ];
      disposables.push(packetGeometry, ...packetMaterials);

      const packets = curves.map((curve, index) => {
        const mesh = new THREE.Mesh(packetGeometry, packetMaterials[index]);
        mesh.castShadow = false;
        root.add(mesh);
        return {
          curve,
          mesh,
          offset: index * 0.29,
          speed: 0.000055 + index * 0.000015,
        };
      });

      const markerGeometry = new THREE.SphereGeometry(0.055, 16, 12);
      const markerMaterial = new THREE.MeshStandardMaterial({ color: accent, roughness: 0.3, metalness: 0.18 });
      disposables.push(markerGeometry, markerMaterial);

      for (let i = 0; i < 48; i += 1) {
        const marker = new THREE.Mesh(markerGeometry, markerMaterial);
        const x = -5.7 + (i % 12) * 1.04;
        const y = -1.55 + Math.floor(i / 12) * 0.58;
        const z = -0.92 + ((i * 7) % 9) * 0.19;
        marker.position.set(x, y, z);
        marker.scale.setScalar(0.55 + ((i * 13) % 10) / 18);
        root.add(marker);
      }

      let pointerX = 0;
      let pointerY = 0;
      let frame = 0;

      const resize = () => {
        const width = Math.max(1, host.clientWidth);
        const height = Math.max(1, host.clientHeight);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height, false);
      };

      const onPointerMove = (event: PointerEvent) => {
        const rect = host.getBoundingClientRect();
        pointerX = ((event.clientX - rect.left) / Math.max(1, rect.width) - 0.5) * 2;
        pointerY = ((event.clientY - rect.top) / Math.max(1, rect.height) - 0.5) * 2;
      };

      const observer = new ResizeObserver(resize);
      observer.observe(host);
      window.addEventListener("pointermove", onPointerMove, { passive: true });
      resize();

      const animate = (time: number) => {
        root.rotation.y = Math.sin(time * 0.00022) * 0.12 + pointerX * 0.07;
        root.rotation.x = -0.08 + Math.sin(time * 0.00018) * 0.025 - pointerY * 0.025;

        packets.forEach((packet, index) => {
          const t = (packet.offset + time * packet.speed) % 1;
          const point = packet.curve.getPointAt(t);
          const tangent = packet.curve.getTangentAt(t);
          packet.mesh.position.copy(point);
          packet.mesh.rotation.y = Math.atan2(tangent.x, tangent.z);
          packet.mesh.rotation.x = 0.35 + Math.sin(time * 0.003 + index) * 0.18;
        });

        renderer.render(scene, camera);
        frame = window.requestAnimationFrame(animate);
      };

      frame = window.requestAnimationFrame(animate);

      cleanup = () => {
        window.cancelAnimationFrame(frame);
        window.removeEventListener("pointermove", onPointerMove);
        observer.disconnect();
        disposables.forEach((item) => item.dispose());
        renderer.dispose();
      };
    }

    boot();

    return () => {
      mounted = false;
      cleanup?.();
    };
  }, []);

  return <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden="true" />;
}
