// Mirrors the backend rules: 8-128 chars, letters and numbers.
export function passwordProblems(pw) {
  const p = [];
  if (pw.length < 8) p.push('at least 8 characters');
  if (!/[A-Za-z]/.test(pw)) p.push('a letter');
  if (!/\d/.test(pw)) p.push('a number');
  if (pw.length > 128) p.push('at most 128 characters');
  return p;
}

export function passwordStrength(pw) {
  if (!pw) return { level: 0, label: '' };
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score++;
  const level = Math.max(1, Math.min(4, score));
  return { level, label: ['', 'Weak', 'Fair', 'Good', 'Strong'][level] };
}

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
