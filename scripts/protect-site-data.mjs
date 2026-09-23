import { createCipheriv, createDecipheriv, pbkdf2Sync, randomBytes } from 'node:crypto';
import { cp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dataDir = path.join(root, 'data');
const privateStateFile = path.join(dataDir, 'private-state.encrypted.json');
const iterations = 600000;

function password() {
  const value = process.env.SITE_DATA_PASSWORD;
  if (!value) throw new Error('SITE_DATA_PASSWORD is required to protect site data.');
  return value;
}

async function readJson(file) {
  return JSON.parse(await readFile(file, 'utf8'));
}

function encrypt(value, secret) {
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const key = pbkdf2Sync(secret, salt, iterations, 32, 'sha256');
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(value), 'utf8'), cipher.final(), cipher.getAuthTag()]);
  return {
    version: 1,
    algorithm: 'AES-256-GCM',
    kdf: 'PBKDF2-SHA-256',
    iterations,
    salt: salt.toString('base64'),
    iv: iv.toString('base64'),
    ciphertext: ciphertext.toString('base64'),
  };
}

function decrypt(payload, secret) {
  if (payload.version !== 1 || payload.algorithm !== 'AES-256-GCM' || payload.kdf !== 'PBKDF2-SHA-256') {
    throw new Error('Unsupported encrypted data format.');
  }
  const key = pbkdf2Sync(secret, Buffer.from(payload.salt, 'base64'), payload.iterations, 32, 'sha256');
  const encrypted = Buffer.from(payload.ciphertext, 'base64');
  const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(payload.iv, 'base64'));
  decipher.setAuthTag(encrypted.subarray(-16));
  return JSON.parse(Buffer.concat([decipher.update(encrypted.subarray(0, -16)), decipher.final()]).toString('utf8'));
}

async function restorePrivateState(secret) {
  try {
    const state = decrypt(await readJson(privateStateFile), secret);
    await Promise.all([
      writeFile(path.join(dataDir, 'announcements.json'), `${JSON.stringify(state.announcements, null, 2)}\n`),
      writeFile(path.join(dataDir, 'source-status.json'), `${JSON.stringify(state.source_status, null, 2)}\n`),
      writeFile(path.join(dataDir, 'notified.json'), `${JSON.stringify(state.notified, null, 2)}\n`),
    ]);
    console.log('Restored encrypted crawler state.');
  } catch (error) {
    if (error.code === 'ENOENT') {
      console.log('No encrypted crawler state yet; using the initial repository data.');
      return;
    }
    throw error;
  }
}

async function buildProtectedFiles(secret) {
  const [announcements, sourceStatus, notified, manualCheck, sourcesCsv] = await Promise.all([
    readJson(path.join(dataDir, 'announcements.json')),
    readJson(path.join(dataDir, 'source-status.json')),
    readJson(path.join(dataDir, 'notified.json')),
    readJson(path.join(dataDir, 'manual-check.json')),
    readFile(path.join(dataDir, 'sources.csv'), 'utf8'),
  ]);
  const privateState = { announcements, source_status: sourceStatus, notified };
  const siteData = { announcements, source_status: sourceStatus, manual_check: manualCheck, sources_csv: sourcesCsv };

  await writeFile(privateStateFile, `${JSON.stringify(encrypt(privateState, secret), null, 2)}\n`);
  const siteDir = path.join(root, '_site');
  await rm(siteDir, { recursive: true, force: true });
  await mkdir(path.join(siteDir, 'data'), { recursive: true });
  await Promise.all([
    cp(path.join(root, 'index.html'), path.join(siteDir, 'index.html')),
    cp(path.join(root, 'app.js'), path.join(siteDir, 'app.js')),
    cp(path.join(root, 'styles.css'), path.join(siteDir, 'styles.css')),
    writeFile(path.join(siteDir, 'data', 'site-data.encrypted.json'), `${JSON.stringify(encrypt(siteData, secret), null, 2)}\n`),
  ]);
  console.log('Built encrypted site data.');
}

const mode = process.argv[2];
const secret = password();
if (mode === 'restore') {
  await restorePrivateState(secret);
} else if (mode === 'build') {
  await buildProtectedFiles(secret);
} else {
  throw new Error('Use: node scripts/protect-site-data.mjs <restore|build>');
}
