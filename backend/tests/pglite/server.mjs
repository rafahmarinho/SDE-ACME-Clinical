// Local PostgreSQL (PGlite, in-memory) exposed over TCP for the test suite and offline demo.
// TEST / OFFLINE-DEMO TOOLING ONLY.
import { PGlite } from '@electric-sql/pglite'
import { PGLiteSocketServer } from '@electric-sql/pglite-socket'

const port = Number(process.argv[2] || 54329)
const db = await PGlite.create()
const server = new PGLiteSocketServer({ db, host: '127.0.0.1', port })
await server.start()
console.log(`PGLITE_READY ${port}`)
const stop = async () => { try { await server.stop(); await db.close() } finally { process.exit(0) } }
process.on('SIGINT', stop)
process.on('SIGTERM', stop)
