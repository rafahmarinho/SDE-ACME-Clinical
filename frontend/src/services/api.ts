import { config } from '../lib/config'
import { supabase } from './supabase'

export interface FieldError {
  field: string
  message: string
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fields: FieldError[]
  readonly requestId?: string

  constructor(status: number, code: string, message: string, fields: FieldError[] = [], requestId?: string) {
    super(message)
    this.status = status
    this.code = code
    this.fields = fields
    this.requestId = requestId
  }
}

type SessionListener = (code: string, message: string) => void
let sessionListener: SessionListener | null = null

/** The auth provider registers here to react to expired / revoked sessions and MFA step-up. */
export function onSessionProblem(listener: SessionListener | null): void {
  sessionListener = listener
}

const SESSION_CODES = new Set(['session_expired', 'session_revoked', 'invalid_token', 'account_inactive', 'mfa_required'])

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  form?: FormData
  auth?: boolean
  signal?: AbortSignal
}

async function accessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token ?? null
}

async function send(path: string, options: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = {}
  if (options.auth !== false) {
    const token = await accessToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  let body: BodyInit | undefined
  if (options.form) body = options.form
  else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }
  let response: Response
  try {
    response = await fetch(`${config.apiUrl}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: options.signal,
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
    })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new ApiError(0, 'network_error', 'Cannot reach the ACME Clinical service. Check your connection.')
  }
  if (!response.ok) {
    let payload: { error?: { code?: string; message?: string; fields?: FieldError[]; request_id?: string } } = {}
    try {
      payload = await response.json()
    } catch {
      /* non-JSON error */
    }
    const err = payload.error ?? {}
    const apiError = new ApiError(
      response.status,
      err.code ?? 'error',
      err.message ?? 'The request failed. Please try again.',
      err.fields ?? [],
      err.request_id,
    )
    if (response.status === 401 && SESSION_CODES.has(apiError.code) && sessionListener) {
      sessionListener(apiError.code, apiError.message)
    }
    throw apiError
  }
  return response
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Downloads a file through the API (bearer-authenticated) and hands it to the browser. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const response = await send(path)
  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const match = /filename="([^"]+)"/.exec(disposition)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = match?.[1] ?? fallbackName
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.fields.length) return `${error.message} ${error.fields.map((f) => `${f.field}: ${f.message}`).join('; ')}`
    return error.message
  }
  return 'Something went wrong. Please try again.'
}
