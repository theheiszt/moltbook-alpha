import React from 'react';

export const MoltLogoMark: React.FC<{
  size?: 'sm' | 'md' | 'lg';
  showStackedText?: boolean;
  showTagline?: boolean;
}> = ({ size = 'md', showStackedText = false, showTagline = false }) => {
  const iconDim =
    size === 'sm' ? 'w-7 h-7' : size === 'lg' ? 'w-11 h-11' : 'w-8 h-8';
  return (
    <div
      className={`flex items-center ${
        showStackedText ? 'flex-col gap-1' : 'gap-2.5'
      } select-none`}
    >
      <img
        src="/assets/aistudio/icon-192_77302bae.png"
        alt="MoltAlpha Logo"
        width={36}
        height={36}
        className={`${iconDim} shrink-0 object-contain border border-cyan-500/40 bg-[#080d16] cyber-cut-sm`}
      />
      <span
        className={`font-display font-bold tracking-tight whitespace-nowrap ${
          size === 'sm' ? 'text-base' : size === 'lg' ? 'text-2xl' : 'text-lg'
        }`}
      >
        <span className="text-white">Molt</span>
        <span className="bg-gradient-to-r from-cyan-400 via-sky-400 to-purple-400 bg-clip-text text-transparent">
          Alpha
        </span>
      </span>
      {showTagline && (
        <span className="hidden 2xl:inline-block text-[10px] font-mono uppercase tracking-[0.14em] text-[#64748b] border-l border-[#1e293b] pl-3 ml-0.5">
          Autonomous Intelligence
        </span>
      )}
    </div>
  );
};

/**
 * High-precision SVG recreation of the uploaded "sent sheild.png" MoltAlpha Sentinel Shield logo:
 * - Segmented metallic chrome shield with cyan & violet neon rim lighting
 * - 4 connected isometric wireframe cubes in a diamond network at the top crest
 * - 3D beveled metallic silver 'M' and 'A' interlocking monogram with cyan core triangle
 * - Autonomous cybernetic agent visor head in the center
 * - Circuit-traced cyan padlock sub-shield at the bottom point
 * - Glowing circular holo-pedestal & "MoltAlpha Sentinel" italic wordmark
 */
export const SentinelShieldSvg: React.FC<{
  showWordmark?: boolean;
  className?: string;
}> = ({ showWordmark = true, className = 'w-full h-full' }) => (
  <svg
    viewBox={showWordmark ? '0 0 400 390' : '0 0 400 320'}
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    role="img"
    aria-label="MoltAlpha Sentinel Shield Logo"
  >
    <defs>
      <linearGradient id="sentBg" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#040914" />
        <stop offset="60%" stopColor="#061226" />
        <stop offset="100%" stopColor="#030710" />
      </linearGradient>
      <linearGradient id="chromeFrame" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="#F8FAFC" />
        <stop offset="30%" stopColor="#94A3B8" />
        <stop offset="55%" stopColor="#E2E8F0" />
        <stop offset="80%" stopColor="#475569" />
        <stop offset="100%" stopColor="#CBD5E1" />
      </linearGradient>
      <linearGradient id="chromeLeft" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="#FFFFFF" />
        <stop offset="50%" stopColor="#CBD5E1" />
        <stop offset="100%" stopColor="#64748B" />
      </linearGradient>
      <linearGradient id="chromeRight" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="#94A3B8" />
        <stop offset="55%" stopColor="#475569" />
        <stop offset="100%" stopColor="#1E293B" />
      </linearGradient>
      <linearGradient id="shieldRimGlow" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="#00F5FF" />
        <stop offset="50%" stopColor="#38BDF8" />
        <stop offset="85%" stopColor="#A855F7" />
        <stop offset="100%" stopColor="#00F5FF" />
      </linearGradient>
      <radialGradient id="coreGlow" cx="50%" cy="48%" r="48%">
        <stop offset="0%" stopColor="#00F0FF" stopOpacity="0.36" />
        <stop offset="60%" stopColor="#0284C7" stopOpacity="0.14" />
        <stop offset="100%" stopColor="#030712" stopOpacity="0" />
      </radialGradient>
    </defs>

    {/* Ambient Core Halo */}
    <circle cx="200" cy="165" r="150" fill="url(#coreGlow)" />

    {/* Holographic Base Ring under Shield */}
    <ellipse
      cx="200"
      cy="304"
      rx="148"
      ry="18"
      stroke="#00F0FF"
      strokeOpacity="0.55"
      strokeWidth="1.5"
      strokeDasharray="8 6"
    />
    <ellipse
      cx="200"
      cy="304"
      rx="112"
      ry="11"
      fill="rgba(0, 240, 255, 0.10)"
      stroke="#38BDF8"
      strokeOpacity="0.7"
      strokeWidth="1.2"
    />

    {/* Outer Neon Rim Shield */}
    <path
      d="M200 22 L316 68 L316 164 C316 226 266 272 200 302 C134 272 84 226 84 164 L84 68 Z"
      fill="#050C1A"
      stroke="url(#shieldRimGlow)"
      strokeWidth="4.5"
    />

    {/* Segmented Metallic Chrome Shield Bezel */}
    <path
      d="M200 30 L306 73 L306 162 C306 219 260 262 200 290 C140 262 94 219 94 162 L94 73 Z"
      fill="url(#sentBg)"
      stroke="url(#chromeFrame)"
      strokeWidth="8"
    />

    {/* Inner Cyan/Violet Accent Edge */}
    <path
      d="M200 40 L295 79 L295 160 C295 212 253 252 200 278 C147 252 105 212 105 160 L105 79 Z"
      fill="none"
      stroke="url(#shieldRimGlow)"
      strokeWidth="1.5"
      strokeOpacity="0.75"
    />

    {/* Digital Matrix Pixels on Left & Right Upper Corners */}
    <g fill="#00F0FF" opacity="0.8">
      <rect x="108" y="88" width="5" height="5" />
      <rect x="116" y="96" width="4" height="4" />
      <rect x="108" y="102" width="6" height="6" />
      <rect x="284" y="94" width="5" height="5" />
      <rect x="276" y="102" width="4" height="4" />
      <rect x="284" y="108" width="6" height="6" />
    </g>

    {/* 4 Connected Isometric Wireframe Cubes at Top Crest */}
    <g stroke="#00F5FF" strokeWidth="1.5" fill="rgba(6, 182, 212, 0.15)">
      <line x1="200" y1="68" x2="172" y2="84" stroke="#38BDF8" strokeWidth="1.4" />
      <line x1="200" y1="68" x2="228" y2="84" stroke="#38BDF8" strokeWidth="1.4" />
      <line x1="172" y1="84" x2="200" y2="100" stroke="#38BDF8" strokeWidth="1.4" />
      <line x1="228" y1="84" x2="200" y2="100" stroke="#38BDF8" strokeWidth="1.4" />

      <polygon points="200,52 209,57 200,62 191,57" />
      <polygon points="191,57 200,62 200,72 191,67" />
      <polygon points="209,57 200,62 200,72 209,67" />

      <polygon points="172,72 181,77 172,82 163,77" />
      <polygon points="163,77 172,82 172,92 163,87" />
      <polygon points="181,77 172,82 172,92 181,87" />

      <polygon points="228,72 237,77 228,82 219,77" />
      <polygon points="219,77 228,82 228,92 219,87" />
      <polygon points="237,77 228,82 228,92 237,87" />

      <polygon points="200,88 210,93 200,98 190,93" />
      <polygon points="190,93 200,98 200,109 190,104" />
      <polygon points="210,93 200,98 200,109 210,104" />
    </g>

    {/* 3D Beveled Metallic Silver 'M' and 'A' Monogram */}
    <g>
      <polygon
        points="132,96 154,112 154,186 132,202"
        fill="url(#chromeLeft)"
        stroke="#E2E8F0"
        strokeWidth="1"
      />
      <polygon
        points="132,96 192,140 180,156 154,136"
        fill="url(#chromeFrame)"
        stroke="#00F0FF"
        strokeWidth="0.9"
      />
      <polygon
        points="268,96 246,112 246,186 268,202"
        fill="url(#chromeRight)"
        stroke="#CBD5E1"
        strokeWidth="1"
      />
      <polygon
        points="268,96 208,140 220,156 246,136"
        fill="url(#chromeLeft)"
        stroke="#00F0FF"
        strokeWidth="0.9"
      />
      <polygon
        points="200,126 154,204 175,204 200,160 225,204 246,204"
        fill="url(#chromeLeft)"
        stroke="#FFFFFF"
        strokeWidth="1.2"
      />
      <polygon
        points="200,168 185,192 215,192"
        fill="#00F5FF"
        stroke="#FFFFFF"
        strokeWidth="0.8"
      />
    </g>

    {/* Autonomous Agent Robot Head with Glowing Cyan Visor Eyes */}
    <g>
      <rect
        x="182"
        y="202"
        width="36"
        height="26"
        rx="12"
        fill="url(#chromeFrame)"
        stroke="#00F0FF"
        strokeWidth="1.2"
      />
      <rect x="177" y="209" width="4" height="12" rx="2" fill="#94A3B8" stroke="#00F0FF" strokeWidth="0.8" />
      <rect x="219" y="209" width="4" height="12" rx="2" fill="#94A3B8" stroke="#00F0FF" strokeWidth="0.8" />
      <rect x="186" y="209" width="28" height="12" rx="5" fill="#040B1A" stroke="#38BDF8" strokeWidth="1" />
      <polygon points="190,215 197,213 196,217" fill="#00F5FF" />
      <polygon points="210,215 203,213 204,217" fill="#00F5FF" />
    </g>

    {/* Circuit Traces Radiating to Bottom Padlock Shield */}
    <g stroke="#00F5FF" strokeWidth="1.5" fill="none">
      <polyline points="138,214 156,214 166,226 184,226" />
      <polyline points="262,214 244,214 234,226 216,226" />
      <polyline points="146,238 164,238 175,248 184,248" />
      <polyline points="254,238 236,238 225,248 216,248" />
      <circle cx="136" cy="214" r="2.5" fill="#040B1A" />
      <circle cx="264" cy="214" r="2.5" fill="#040B1A" />
      <circle cx="144" cy="238" r="2.5" fill="#040B1A" />
      <circle cx="256" cy="238" r="2.5" fill="#040B1A" />
    </g>

    {/* Bottom Cyan Mini-Shield with Padlock */}
    <g>
      <path
        d="M200 232 L218 239 L218 255 C218 266 210 274 200 279 C190 274 182 266 182 255 L182 239 Z"
        fill="#061A33"
        stroke="#00F5FF"
        strokeWidth="2"
      />
      <path
        d="M195 251 V246 C195 243.2 197.2 241 200 241 C202.8 241 205 243.2 205 246 V251"
        stroke="#00F5FF"
        strokeWidth="2"
        fill="none"
      />
      <rect x="192" y="251" width="16" height="14" rx="2" fill="#00F5FF" />
      <circle cx="200" cy="256.5" r="1.8" fill="#04131D" />
      <rect x="199" y="257.5" width="2" height="4" fill="#04131D" />
    </g>

    {/* "MoltAlpha Sentinel" Wordmark below Shield */}
    {showWordmark && (
      <g>
        <text
          x="200"
          y="354"
          textAnchor="middle"
          fontFamily="Outfit, sans-serif"
          fontWeight="800"
          fontStyle="italic"
          fontSize="33"
          letterSpacing="0.5"
        >
          <tspan fill="#F8FAFC">MoltAlpha </tspan>
          <tspan fill="#22D3EE">Sentinel</tspan>
        </text>
      </g>
    )}
  </svg>
);

export const SentinelShieldBadge: React.FC<{
  size?: 'xs' | 'sm' | 'md' | 'lg';
  className?: string;
}> = ({ size = 'sm', className = '' }) => {
  const dim =
    size === 'xs'
      ? 'w-5 h-5'
      : size === 'sm'
        ? 'w-8 h-8'
        : size === 'md'
          ? 'w-11 h-11'
          : 'w-24 h-24';
  return (
    <div
      className={`relative shrink-0 overflow-hidden border border-cyan-400/60 bg-[#050814] cyber-cut-sm flex items-center justify-center shadow-[0_0_16px_rgba(6,182,212,0.35)] ${dim} ${className}`}
    >
      <SentinelShieldSvg showWordmark={false} className="w-full h-full" />
    </div>
  );
};

/**
 * Clean, unframed 3D Isometric Neon Data Core / Sentinel Shield hero graphic
 * that blends organically into the dark cybernetic canvas without an inner box frame.
 */
export const IsometricChipGraphic: React.FC<{
  className?: string;
  compact?: boolean;
  variant?: 'datacore' | 'emblem' | 'sentinel';
}> = ({ className = '', compact = false, variant = 'datacore' }) => {
  const imgSrc =
    variant === 'emblem'
      ? '/assets/aistudio/logo-hero-640_91e2b88d.webp'
      : '/assets/aistudio/MoltAlpha_Neon_Data_Core_c2ac8cd2.png';

  if (variant === 'sentinel') {
    return (
      <div
        className={`relative flex items-center justify-center select-none pointer-events-none ${
          compact ? 'w-[180px] h-[180px]' : 'w-full max-w-[380px] h-[270px]'
        } ${className}`}
      >
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(6,182,212,0.22)_0%,rgba(139,92,246,0.12)_45%,transparent_72%)] blur-xl" />
        <SentinelShieldSvg showWordmark className="relative z-10 w-full h-full drop-shadow-[0_0_24px_rgba(6,182,212,0.4)]" />
      </div>
    );
  }

  return (
    <div
      className={`relative flex items-center justify-center select-none pointer-events-none ${
        compact ? 'w-full max-w-[270px]' : 'w-full max-w-[540px]'
      } ${className}`}
    >
      {/* Ambient cyan/violet radial halo behind the 3D isometric chip */}
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(6,182,212,0.28)_0%,rgba(168,85,247,0.18)_45%,transparent_75%)] blur-2xl" />
      <img
        src={imgSrc}
        alt="MoltAlpha 3D Isometric Neon Data Core"
        className={`relative z-10 w-full ${
          compact ? 'h-[185px]' : 'h-[270px] sm:h-[320px]'
        } object-cover object-center [mask-image:radial-gradient(ellipse_78%_74%_at_50%_50%,black_52%,transparent_100%)]`}
      />
    </div>
  );
};

export const VerifiedCubeBadge: React.FC = () => (
  <div className="relative w-16 h-16 shrink-0 molt-card p-1 flex items-center justify-center">
    <SentinelShieldSvg showWordmark={false} className="w-full h-full" />
    <span className="absolute bottom-0.5 right-0.5 w-4 h-4 bg-emerald-500 text-[#04131d] font-mono font-bold text-[10px] flex items-center justify-center">
      ✓
    </span>
  </div>
);
