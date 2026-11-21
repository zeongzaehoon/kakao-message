// Packaging only; the application and image processing run entirely in Rust.
import { execFileSync, spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, lstatSync, readFileSync, readdirSync, renameSync, rmSync, mkdirSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

if (process.platform !== 'darwin') {
    throw new Error('Mac 전용 빌드입니다. Windows에서는 scripts/build_windows.bat을 사용하세요.');
}
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const config = JSON.parse(readFileSync(join(root, 'src-tauri/tauri.conf.json'), 'utf8'));
const version = config.version;
if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error('배포 버전 형식이 잘못됐습니다.');
const target = process.env.CARGO_TARGET_DIR
    ? resolve(root, process.env.CARGO_TARGET_DIR)
    : join(root, 'src-tauri/target');
const bundle = join(target, 'release/bundle');
const app = join(bundle, 'macos/Kakao Friend Sender.app');
const releases = join(root, 'dist/releases', version);
const registry = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister';
const run = (command, args) => execFileSync(command, args, { cwd: root, stdio: 'inherit', env: { ...process.env, CARGO_TARGET_DIR: target } });
const readPlist = (path, key) => execFileSync('/usr/libexec/PlistBuddy', ['-c', `Print :${key}`, join(path, 'Contents/Info.plist')], { encoding: 'utf8' }).trim();

function removeIntermediateApp() {
    if (!existsSync(app)) return;
    if (lstatSync(app).isSymbolicLink() || readPlist(app, 'CFBundleIdentifier') !== config.identifier) {
        throw new Error(`예상하지 않은 앱이므로 삭제하지 않았습니다: ${app}`);
    }
    // Refuse to remove a development app that someone opened during packaging.
    const processes = execFileSync('/bin/ps', ['-axo', 'command='], { encoding: 'utf8' });
    if (processes.split('\n').some(line => line.startsWith(join(app, 'Contents/MacOS/')))) {
        throw new Error('중간 빌드 앱이 실행 중입니다. 종료한 뒤 다시 빌드하세요.');
    }
    spawnSync(registry, ['-u', app], { stdio: 'ignore' });
    rmSync(app, { recursive: true });
}

function unregisterMissingCopies() {
    const dump = spawnSync(registry, ['-dump'], { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
    if (dump.status !== 0) return;
    for (const block of dump.stdout.split('--------------------------------------------------------------------------------')) {
        const identifier = /^identifier:\s+(\S+)\s*$/m.exec(block)?.[1];
        if (![config.identifier, `${config.identifier}.runtime`].includes(identifier)) continue;
        const path = /^path:\s+(.+?)\s+\(0x[0-9a-f]+\)/m.exec(block)?.[1];
        if (path && !existsSync(path)) spawnSync(registry, ['-u', path], { stdio: 'ignore' });
    }
}

try {
    mkdirSync(join(bundle, 'macos'), { recursive: true });
    writeFileSync(join(bundle, 'macos/.metadata_never_index'), '');
    run(join(root, 'node_modules/.bin/tauri'), ['build', '--bundles', 'app,dmg', '--', '--locked']);
    if (readPlist(app, 'CFBundleIdentifier') !== config.identifier || readPlist(app, 'CFBundleShortVersionString') !== version) {
        throw new Error('빌드 앱의 식별자·버전이 배포 설정과 다릅니다.');
    }
    run('/usr/bin/codesign', ['--verify', '--deep', '--strict', app]);
    mkdirSync(releases, { recursive: true });
    run(join(app, 'Contents/MacOS/kakao-friend-sender'), ['--self-test', join(releases, 'rust-self-test.json')]);
    run(join(app, 'Contents/MacOS/kakao-friend-sender'), ['--ui-self-test', join(releases, 'ui-self-test.json'), 'composer', 'compact']);
    if (!JSON.parse(readFileSync(join(releases, 'ui-self-test.json'), 'utf8')).ok) throw new Error('화면 렌더링 검사 실패');
    const architecture = process.arch === 'arm64' ? 'aarch64' : 'x64';
    const name = `Kakao Friend Sender_${version}_${architecture}.dmg`;
    const dmg = join(bundle, 'dmg', name);
    if (!readdirSync(join(bundle, 'dmg')).includes(name)) throw new Error('현재 버전 DMG가 없습니다.');
    run('/usr/bin/hdiutil', ['verify', dmg]);
    const destination = join(releases, `Kakao-Friend-Sender-${version}-macos-${process.arch}.dmg`);
    copyFileSync(dmg, `${destination}.partial`);
    renameSync(`${destination}.partial`, destination);
    writeFileSync(join(releases, 'SHA256SUMS.txt'), `${createHash('sha256').update(readFileSync(destination)).digest('hex')}  ${destination.split('/').at(-1)}\n`);
    rmSync(dmg);
    console.log(`배포 파일: ${destination}`);
} finally {
    // Keep runnable app bundles only in /Applications, not in build or backup folders.
    removeIntermediateApp();
    unregisterMissingCopies();
}
