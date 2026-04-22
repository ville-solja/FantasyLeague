const { useState } = React;

function Header({ user = "muffa_caster", tokens = 12 }) {
  return (
    <header style={headerStyles.root}>
      <div style={headerStyles.left}>
        <img src="../../assets/logo_kanaliiga_primary.png" alt="Kanaliiga" style={headerStyles.logo}/>
        <div>
          <div style={headerStyles.eyebrow}>CORPORATE ESPORTS LEAGUE</div>
          <div style={headerStyles.title}>KANALIIGA FANTASY</div>
        </div>
        <span style={headerStyles.season}>S14 · DOTA 2</span>
      </div>
      <div style={headerStyles.right}>
        <div style={headerStyles.tokens}>
          <i data-lucide="coins" width="16" height="16" style={{stroke: 'var(--accent)'}}></i>
          <span style={headerStyles.tokenNum}>{tokens}</span>
          <span style={headerStyles.tokenLabel}>Tokens</span>
        </div>
        <button style={headerStyles.account}>{user}</button>
      </div>
    </header>
  );
}

const headerStyles = {
  root: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '18px 28px', borderBottom: '1px solid var(--border)', background: 'var(--k-ink-950)' },
  left: { display: 'flex', alignItems: 'center', gap: 16 },
  logo: { width: 52, height: 52, display: 'block' },
  eyebrow: { fontFamily: 'var(--font-display)', fontSize: 10, letterSpacing: 'var(--tr-widest)', textTransform: 'uppercase', color: 'var(--fg-dim)', fontWeight: 700 },
  title: { fontFamily: 'var(--font-display)', fontSize: 22, letterSpacing: 'var(--tr-wider)', textTransform: 'uppercase', fontWeight: 900, color: 'var(--fg)', lineHeight: 1 },
  season: { fontFamily: 'var(--font-display)', fontSize: 11, letterSpacing: 'var(--tr-widest)', textTransform: 'uppercase', color: 'var(--accent)', padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 2, fontWeight: 700, marginLeft: 6 },
  right: { display: 'flex', alignItems: 'center', gap: 14 },
  tokens: { display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 4 },
  tokenNum: { fontFamily: 'var(--font-display)', fontWeight: 900, color: 'var(--accent)', fontSize: 16 },
  tokenLabel: { fontFamily: 'var(--font-display)', fontSize: 10, letterSpacing: 'var(--tr-widest)', textTransform: 'uppercase', color: 'var(--fg-dim)', fontWeight: 700 },
  account: { fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 12, letterSpacing: 'var(--tr-wider)', textTransform: 'uppercase', background: 'transparent', color: 'var(--fg)', border: '1px solid var(--border)', padding: '8px 14px', borderRadius: 4, cursor: 'pointer' }
};

window.Header = Header;
