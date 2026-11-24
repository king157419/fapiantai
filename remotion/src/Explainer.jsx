import React from 'react';
import {AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';

const PAPER = '#f4eee2';
const INK = '#3a3128';
const INK_SOFT = '#80705e';
const ACCENT = '#d68c34';
const SERIF = '"Noto Serif SC", "Source Han Serif SC", serif';
const SANS = '"Microsoft YaHei", "PingFang SC", sans-serif';

// 三次缓动：起步和收尾都慢，镜头和鼠标都用它
const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

// 关键帧插值（亚像素，不取整，所以平移不会一顿一顿）
function lerpKeys(keys, t, fields) {
  if (!keys.length) return null;
  if (t <= keys[0].t) return keys[0];
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i], b = keys[i + 1];
    if (t >= a.t && t < b.t) {
      const p = ease((t - a.t) / Math.max(1e-6, b.t - a.t));
      const out = {};
      for (const f of fields) {
        out[f] = f === 's' ? Math.exp(Math.log(a[f]) + (Math.log(b[f]) - Math.log(a[f])) * p) : a[f] + (b[f] - a[f]) * p;
      }
      return out;
    }
  }
  return keys[keys.length - 1];
}

function recTimeFor(seg, t, fps) {
  return Math.min(seg.rec_start + (t - seg.start) * (seg.rate || 1), seg.rec_limit - 1 / fps);
}

const Cursor = ({size}) => (
  <svg width={size} height={size * 1.25} viewBox="0 0 24 30" style={{filter: 'drop-shadow(0 2px 3px rgba(0,0,0,.45))'}}>
    <path d="M2 1.5 L2 24 L7.6 18.6 L11.6 28 L15.4 26.4 L11.5 17.2 L19.5 17.2 Z" fill="#fff" stroke="#1d1a17" strokeWidth="1.6" strokeLinejoin="round" />
  </svg>
);

export const Explainer = (props) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const {slug, title, hook, footer, viewport, card, segments, camera, cursor, clicks, keys} = props;
  if (!segments) return <AbsoluteFill style={{background: PAPER}} />;
  const [vw, vh] = viewport;
  const k = card.w / vw; // 录屏 CSS 像素 → 卡片像素
  const rec = staticFile(`${slug}/rec.mp4`);

  // 当前段
  let si = segments.findIndex((s) => t >= s.start && t < s.end);
  if (si < 0) si = t < segments[0].start ? 0 : segments.length - 1;
  const seg = segments[si];
  const recT = recTimeFor(seg, t, fps);
  // 段与段之间录屏跳了一截时，用 8 帧淡入盖过去
  const prev = si > 0 ? segments[si - 1] : null;
  const jump = prev && Math.abs(prev.rec_limit - seg.rec_start) > 0.3 && (prev.rec_start + (prev.end - prev.start) * (prev.rate || 1)) < seg.rec_start - 0.1;
  const fadeIn = jump ? interpolate(t - seg.start, [0, 8 / fps], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 1;
  const prevT = prev ? recTimeFor(prev, prev.end - 1 / fps, fps) : 0;

  // 镜头
  const cam = lerpKeys(camera, t, ['s', 'x', 'y']) || {s: 1, x: vw / 2, y: vh / 2};
  const tx = card.w / 2 - cam.x * k * cam.s;
  const ty = card.h / 2 - cam.y * k * cam.s;

  // 鼠标
  const cur = lerpKeys(cursor, t, ['x', 'y']) || cursor[0];
  const ripple = clicks.map((c) => t - c).filter((d) => d >= 0 && d < 0.55);
  const press = clicks.some((c) => t - c >= -0.06 && t - c < 0.12);

  // 按键提示
  const keyNow = keys.filter((kk) => t - kk.t >= 0 && t - kk.t < 1.3);

  // 字幕
  const lines = segments.flatMap((s) => s.lines);
  let li = -1;
  for (let i = 0; i < lines.length; i++) {
    const nextStart = i + 1 < lines.length ? lines[i + 1].start : lines[i].end + 0.6;
    if (t >= lines[i].start - 0.06 && t < Math.min(nextStart - 0.02, lines[i].end + 0.5)) li = i;
  }
  const line = li >= 0 ? lines[li] : null;
  const subIn = line ? spring({frame: frame - Math.round((line.start - 0.06) * fps), fps, config: {damping: 18, stiffness: 180, mass: 0.6}}) : 0;

  const titleIn = spring({frame, fps, config: {damping: 20, stiffness: 120}});
  const cardIn = spring({frame: frame - 4, fps, config: {damping: 22, stiffness: 110}});
  const progress = t / (props.durationInFrames / fps);

  const vstyle = {position: 'absolute', left: 0, top: 0, width: card.w, height: vh * k, objectFit: 'fill'};
  // 每段一个 Sequence：从 rec_start 开始按 rate 播放录屏，播完停在最后一帧（图片）
  const SegVideo = ({sg, i}) => {
    const f = useCurrentFrame();
    const prevSg = i > 0 ? segments[i - 1] : null;
    const isJump = prevSg && (prevSg.rec_start + (prevSg.playFrames / fps) * (prevSg.rate || 1)) < sg.rec_start - 0.1;
    const op = isJump ? interpolate(f, [0, 8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 1;
    return (
      <>
        {isJump && f < 8 ? <Img src={staticFile(`${slug}/${prevSg.endImg}`)} style={vstyle} /> : null}
        {f < sg.playFrames ? (
          <OffthreadVideo src={rec} muted trimBefore={Math.round(sg.rec_start * fps)} playbackRate={sg.rate || 1} style={{...vstyle, opacity: op}} />
        ) : (
          <Img src={staticFile(`${slug}/${sg.endImg}`)} style={{...vstyle, opacity: op}} />
        )}
      </>
    );
  };

  return (
    <AbsoluteFill style={{background: PAPER}}>
      <Img src={staticFile(`${slug}/paper.png`)} style={{position: 'absolute', width: 1080, height: 1920}} />
      <Audio src={staticFile(`${slug}/narration.wav`)} />

      {/* 标题 */}
      <div style={{position: 'absolute', top: 92, width: 1080, textAlign: 'center', opacity: titleIn, transform: `translateY(${(1 - titleIn) * 24}px)`}}>
        <div style={{fontFamily: SERIF, fontWeight: 700, fontSize: 92, color: INK, letterSpacing: 4}}>{title}</div>
        <div style={{fontFamily: SANS, fontSize: 40, color: INK_SOFT, marginTop: 14}}>{hook}</div>
        <div style={{width: 68, height: 6, borderRadius: 3, background: ACCENT, margin: '26px auto 0'}} />
      </div>

      {/* 卡片 */}
      <div style={{position: 'absolute', left: card.x, top: card.y, width: card.w, height: card.h, borderRadius: card.r,
        transform: `translateY(${(1 - cardIn) * 40}px) scale(${0.97 + 0.03 * cardIn})`, opacity: cardIn,
        boxShadow: '0 22px 50px rgba(120,96,70,.42), 0 0 0 6px #fffcf5', overflow: 'hidden', background: '#0d0f11'}}>
        <div style={{position: 'absolute', left: 0, top: 0, width: card.w, height: card.h, transformOrigin: '0 0',
          transform: `translate(${tx}px, ${ty}px) scale(${cam.s})`}}>
          {segments.map((sg, i) => {
            const from = Math.round(sg.start * fps);
            const to = i + 1 < segments.length ? Math.round(segments[i + 1].start * fps) : props.durationInFrames;
            return (
              <Sequence key={i} from={from} durationInFrames={Math.max(1, to - from)} layout="none">
                <SegVideo sg={sg} i={i} />
              </Sequence>
            );
          })}
          {ripple.map((d, i) => (
            <div key={i} style={{position: 'absolute', left: cur.x * k, top: cur.y * k, width: 0, height: 0}}>
              <div style={{position: 'absolute', left: -60 * d / 0.55, top: -60 * d / 0.55, width: 120 * d / 0.55, height: 120 * d / 0.55,
                borderRadius: '50%', border: `${4 / cam.s}px solid rgba(255,214,150,${0.9 * (1 - d / 0.55)})`, background: `rgba(255,190,110,${0.25 * (1 - d / 0.55)})`}} />
            </div>
          ))}
          <div style={{position: 'absolute', left: cur.x * k - 3, top: cur.y * k - 2, transform: `scale(${(press ? 0.86 : 1) / Math.sqrt(cam.s)})`, transformOrigin: '3px 2px'}}>
            <Cursor size={30} />
          </div>
        </div>
        {/* 进度条 */}
        <div style={{position: 'absolute', left: 0, bottom: 0, height: 5, width: card.w * progress, background: ACCENT, opacity: 0.85}} />
        {keyNow.map((kk, i) => {
          const s = spring({frame: frame - Math.round(kk.t * fps), fps, config: {damping: 14, stiffness: 200}});
          const out = interpolate(t - kk.t, [1.0, 1.3], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
          return (
            <div key={i} style={{position: 'absolute', left: card.w / 2 - 70, bottom: 34, width: 140, height: 84, borderRadius: 18,
              background: 'rgba(255,252,245,.94)', boxShadow: '0 6px 0 #c9b9a3, 0 10px 24px rgba(0,0,0,.35)', display: 'flex',
              alignItems: 'center', justifyContent: 'center', fontFamily: SANS, fontWeight: 700, fontSize: kk.label.length > 1 ? 40 : 54, color: INK,
              transform: `scale(${0.6 + 0.4 * s}) translateY(${(1 - s) * 20}px)`, opacity: Math.min(s, out)}}>{kk.label}</div>
          );
        })}
      </div>

      {/* 字幕 */}
      {line ? (
        <div style={{position: 'absolute', left: 70, width: 940, top: card.sub_y + 10, textAlign: 'center', fontFamily: SANS, fontWeight: 700,
          fontSize: 54, lineHeight: 1.42, color: INK, opacity: subIn, transform: `translateY(${(1 - subIn) * 18}px)`,
          WebkitTextStroke: '12px #fbf7ee', paintOrder: 'stroke fill', whiteSpace: 'pre-line', wordBreak: 'keep-all'}}>{line.display || line.text}</div>
      ) : null}

      <div style={{position: 'absolute', bottom: 46, width: 1080, textAlign: 'center', fontFamily: SANS, fontSize: 30, color: INK_SOFT}}>{footer}</div>
    </AbsoluteFill>
  );
};
