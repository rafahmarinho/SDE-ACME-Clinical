import { Html, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import { useNavigate } from 'react-router'
import type { Group, Mesh, MeshStandardMaterial } from 'three'
import { Vector3 } from 'three'
import type { BedState } from '../services/types'

const COLORS = {
  ok: '#16a34a',
  warning: '#f59e0b',
  critical: '#dc2626',
  advisory: '#2563eb',
  offline: '#6b7280',
  empty: '#cbd5e1',
}

function bedColor(bed: BedState): string {
  if (!bed.monitor_id) return COLORS.empty
  if (bed.connection === 'offline') return COLORS.offline
  if (bed.top_severity) return COLORS[bed.top_severity]
  return COLORS.ok
}

function BedModel({ bed, showClinical }: { bed: BedState; showClinical: boolean }) {
  const navigate = useNavigate()
  const screen = useRef<Mesh>(null)
  const ring = useRef<Mesh>(null)
  const color = bedColor(bed)
  const critical = bed.top_severity === 'critical'
  const facing = bed.pos_z < 0 ? 1 : -1

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime()
    if (screen.current) {
      const mat = screen.current.material as MeshStandardMaterial
      mat.emissiveIntensity = critical ? 0.6 + 0.6 * Math.abs(Math.sin(t * 4)) : 0.55
    }
    if (ring.current) {
      const s = 1 + ((t * 0.9) % 1) * 0.9
      ring.current.scale.set(s, s, s)
      ;(ring.current.material as MeshStandardMaterial).opacity = 0.65 * (1 - ((t * 0.9) % 1))
    }
  })

  const open = () => {
    if (showClinical && bed.patient_id) navigate(`/patients/${bed.patient_id}`)
    else if (bed.monitor_id) navigate(`/devices/${bed.monitor_id}`)
  }
  const name = showClinical && bed.first_name ? `${bed.first_name} ${bed.last_name ?? ''}` : bed.occupied ? 'Occupied' : 'Empty'

  return (
    <group position={[bed.pos_x, 0, bed.pos_z]} onClick={(e) => (e.stopPropagation(), open())}>
      {/* floor bay */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.005, 0]} receiveShadow>
        <planeGeometry args={[2.8, 3.6]} />
        <meshStandardMaterial color={bed.top_severity === 'critical' ? '#fee2e2' : '#ffffff'} />
      </mesh>
      {/* bed frame + mattress + pillow */}
      <mesh position={[0, 0.35, 0]} castShadow>
        <boxGeometry args={[1.1, 0.3, 2.1]} />
        <meshStandardMaterial color="#e2e8f0" />
      </mesh>
      <mesh position={[0, 0.55, 0]} castShadow>
        <boxGeometry args={[1.0, 0.14, 2.0]} />
        <meshStandardMaterial color={bed.occupied ? '#dbeafe' : '#f1f5f9'} />
      </mesh>
      <mesh position={[0, 0.66, -0.75 * facing]}>
        <boxGeometry args={[0.7, 0.1, 0.35]} />
        <meshStandardMaterial color="#ffffff" />
      </mesh>
      {bed.occupied && (
        <mesh position={[0, 0.72, 0.15 * facing]}>
          <capsuleGeometry args={[0.22, 0.9, 6, 12]} />
          <meshStandardMaterial color="#93c5fd" />
        </mesh>
      )}
      {/* monitor pole + screen */}
      {bed.monitor_id && (
        <group position={[0.85, 0, -0.9 * facing]}>
          <mesh position={[0, 0.8, 0]}>
            <cylinderGeometry args={[0.03, 0.03, 1.6]} />
            <meshStandardMaterial color="#94a3b8" />
          </mesh>
          <mesh ref={screen} position={[0, 1.55, 0]}>
            <boxGeometry args={[0.55, 0.38, 0.08]} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.55} />
          </mesh>
        </group>
      )}
      {critical && (
        <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
          <ringGeometry args={[1.25, 1.4, 48]} />
          <meshStandardMaterial color={COLORS.critical} transparent opacity={0.6} />
        </mesh>
      )}
      <Html position={[0, 2.3, 0]} center distanceFactor={10} zIndexRange={[10, 0]}>
        <div className="ward3d-label" onClick={open} title={name}>
          <div>{bed.label}</div>
          {showClinical && bed.spo2 != null && (
            <div className="num" style={{ color: bed.top_severity ? COLORS[bed.top_severity] : '#0f7b4f' }}>
              SpO₂ {bed.spo2} · HR {bed.heart_rate ?? '--'}
            </div>
          )}
        </div>
      </Html>
    </group>
  )
}

/** Staff avatar that walks from the nurses' station to the bed that needs attention. */
function Responder({ target, color, offset }: { target: Vector3 | null; color: string; offset: number }) {
  const ref = useRef<Group>(null)
  const home = useMemo(() => new Vector3(offset, 0, 1.3), [offset])
  useFrame(({ clock }, delta) => {
    const g = ref.current
    if (!g) return
    // stand at the side of the bed, on the aisle side
    const goal = target ? target.clone().add(new Vector3(-0.95, 0, target.z < 0 ? 1.0 : -1.0)) : home
    const dir = goal.clone().sub(g.position)
    const dist = dir.length()
    if (dist > 0.05) {
      dir.normalize().multiplyScalar(Math.min(dist, delta * 3.2))
      g.position.add(dir)
      g.position.y = Math.abs(Math.sin(clock.getElapsedTime() * 9)) * 0.06
      g.lookAt(goal.x, 0, goal.z)
    } else {
      g.position.y = 0
    }
  })
  return (
    <group ref={ref} position={[offset, 0, 1.3]}>
      <mesh position={[0, 0.75, 0]} castShadow>
        <capsuleGeometry args={[0.22, 0.8, 6, 12]} />
        <meshStandardMaterial color={color} />
      </mesh>
      <mesh position={[0, 1.45, 0]} castShadow>
        <sphereGeometry args={[0.2, 16, 16]} />
        <meshStandardMaterial color="#f5d0b5" />
      </mesh>
    </group>
  )
}

export default function Ward3D({ beds, showClinical }: { beds: BedState[]; showClinical: boolean }) {
  const clinicalTargets = beds
    .filter((b) => (b.alarms ?? []).some((a) => a.category === 'physiological' && !a.acknowledged))
    .sort((a, b) => (a.top_severity === 'critical' ? -1 : 0) - (b.top_severity === 'critical' ? -1 : 0))
  const techTargets = beds.filter((b) => (b.alarms ?? []).some((a) => a.category === 'technical'))
  const pos = (b: BedState | undefined) => (b ? new Vector3(b.pos_x, 0, b.pos_z) : null)

  return (
    <div className="ward3d">
      <Canvas shadows camera={{ position: [0, 12, 13], fov: 50 }} dpr={[1, 2]}>
        <color attach="background" args={['#f3f6fb']} />
        <ambientLight intensity={0.75} />
        <directionalLight position={[8, 14, 6]} intensity={1.1} castShadow shadow-mapSize={[1024, 1024]} />
        <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <planeGeometry args={[26, 16]} />
          <meshStandardMaterial color="#eef2f7" />
        </mesh>
        {/* nurses' station */}
        <mesh position={[0, 0.5, 0]} castShadow>
          <boxGeometry args={[4.5, 1, 1.2]} />
          <meshStandardMaterial color="#0b1f3a" />
        </mesh>
        <Html position={[0, 1.4, 0]} center distanceFactor={14}>
          <div className="ward3d-label">Nurses’ station · Ward 4B</div>
        </Html>
        {[-8, 8].map((z) => (
          <mesh key={z} position={[0, 1, z / 1.45]}>
            <boxGeometry args={[26, 2, 0.15]} />
            <meshStandardMaterial color="#ffffff" />
          </mesh>
        ))}
        {beds.map((bed) => (
          <BedModel key={bed.bed_id} bed={bed} showClinical={showClinical} />
        ))}
        <Responder target={pos(clinicalTargets[0])} color="#0e7c86" offset={-1.4} />
        <Responder target={pos(clinicalTargets[1])} color="#1d5fbf" offset={-0.4} />
        <Responder target={pos(techTargets[0])} color="#ea580c" offset={1.4} />
        <OrbitControls enablePan={false} minDistance={8} maxDistance={30} maxPolarAngle={Math.PI / 2.3} />
      </Canvas>
      <div className="ward3d-legend">
        <span className="row" style={{ gap: 6 }}>
          <span className="dot" style={{ color: COLORS.ok }} /> Stable
        </span>
        <span className="row" style={{ gap: 6 }}>
          <span className="dot" style={{ color: COLORS.warning }} /> Warning
        </span>
        <span className="row" style={{ gap: 6 }}>
          <span className="dot" style={{ color: COLORS.critical }} /> Critical
        </span>
        <span className="row" style={{ gap: 6 }}>
          <span className="dot" style={{ color: COLORS.offline }} /> Offline
        </span>
        <span className="muted">Teal/blue: nurses · Orange: biomedical technician</span>
      </div>
    </div>
  )
}
