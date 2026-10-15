/** Client-side hints that mirror the server policy (the API remains the authority). */
export function passwordIssues(password: string, minLength = 12): string[] {
  const issues: string[] = []
  if (password.length < minLength) issues.push(`at least ${minLength} characters`)
  if (!/[a-z]/.test(password)) issues.push('a lowercase letter')
  if (!/[A-Z]/.test(password)) issues.push('an uppercase letter')
  if (!/[0-9]/.test(password)) issues.push('a number')
  if (!/[^A-Za-z0-9\s]/.test(password)) issues.push('a symbol')
  return issues
}
