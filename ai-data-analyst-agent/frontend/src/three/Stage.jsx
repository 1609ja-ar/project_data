// Shared look for the 3D charts: a key light that casts real soft shadows, fill and rim lights, a small
// studio environment built in the browser (no HDR download) for reflections, contact shadows for grounding,
// and a solid platform with engraved grid lines for the columns to stand on.
import { ContactShadows, Environment, Lightformer, RoundedBox } from '@react-three/drei';

export default function Stage({ shadowY = 0, shadowScale = 14, mode = 'full', reach = 8 }) {
  const map = mode === 'lite' ? 1024 : 2048;
  return (
    <>
      <hemisphereLight args={['#ffffff', '#9aa3b5', 0.55]} />
      <directionalLight castShadow position={[5, 9, 6]} intensity={1.7} shadow-mapSize-width={map} shadow-mapSize-height={map}
        shadow-bias={-0.0004} shadow-normalBias={0.03} shadow-radius={6}>
        <orthographicCamera attach="shadow-camera" args={[-reach, reach, reach, -reach, 0.5, 40]} />
      </directionalLight>
      <directionalLight position={[-7, 4, -5]} intensity={0.45} color="#c8d4ff" />
      <directionalLight position={[0, 3, -9]} intensity={0.35} />
      {mode !== 'lite' && (
        <Environment resolution={256} frames={1}>
          <Lightformer form="rect" intensity={2.4} position={[0, 6, 6]} scale={[12, 4, 1]} />
          <Lightformer form="rect" intensity={1} position={[-7, 2, 0]} rotation-y={Math.PI / 2} scale={[8, 4, 1]} />
          <Lightformer form="rect" intensity={0.8} position={[7, 2, -2]} rotation-y={-Math.PI / 2} scale={[8, 4, 1]} />
          <Lightformer form="ring" intensity={1.4} position={[3, 5, -4]} scale={2} />
        </Environment>
      )}
      <ContactShadows position={[0, shadowY, 0]} opacity={0.32} scale={shadowScale} blur={2.8} far={3.5} resolution={mode === 'lite' ? 256 : 512} />
    </>
  );
}

/** A rounded slab whose top surface is at y = 0, with engraved lines between the rows and columns. */
export function Platform({ width, depth, colors, xLines = [], zLines = [] }) {
  const dark = colors.theme === 'dark';
  const top = dark ? '#1f232b' : '#f3f4f7';
  const line = dark ? '#2c313b' : '#dde1e8';
  return (
    <group>
      <RoundedBox args={[width, 0.16, depth]} radius={0.07} smoothness={4} position={[0, -0.08, 0]} receiveShadow>
        <meshPhysicalMaterial color={top} roughness={0.75} metalness={0} clearcoat={0.25} clearcoatRoughness={0.6} />
      </RoundedBox>
      {xLines.map((x) => (
        <mesh key={`x${x}`} position={[x, 0.002, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <planeGeometry args={[0.012, depth - 0.3]} />
          <meshStandardMaterial color={line} />
        </mesh>
      ))}
      {zLines.map((z) => (
        <mesh key={`z${z}`} position={[0, 0.002, z]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <planeGeometry args={[width - 0.3, 0.012]} />
          <meshStandardMaterial color={line} />
        </mesh>
      ))}
    </group>
  );
}
