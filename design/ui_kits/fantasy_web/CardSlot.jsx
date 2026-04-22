function CardSlot({ player = "—", team = "", pts = "—", rarity = "common", empty = false }) {
  if (empty) {
    return <div style={cardStyles.empty}><span style={{color: 'var(--fg-dim)', fontFamily: 'var(--font-display)', fontSize: 10, letterSpacing: 'var(--tr-widest)', textTransform: 'uppercase'}}>Empty</span></div>;
  }
  const rar = cardStyles.rarity[rarity];
  const initials = player.slice(0,5).toUpperCase();
  return (
    <div style={cardStyles.slot}>
      <div style={{...cardStyles.art, ...rar.art}}>
        <span style={cardStyles.initials}>{initials}</span>
      </div>
      <span style={{...cardStyles.rar, color: rar.c}}>{rarity}</span>
      <span style={cardStyles.name}>{player}</span>
      {team && <span style={cardStyles.team}>{team}</span>}
      <span style={{...cardStyles.pts, color: rar.c}}>{pts}</span>
    </div>
  );
}

const cardStyles = {
  slot: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, padding: '10px 8px', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', width: 140 },
  empty: { width: 140, height: 240, border: '2px dashed var(--border)', borderRadius: 'var(--r-md)', display: 'flex', alignItems: 'center', justifyContent: 'center' },
  art: { width: 118, height: 164, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center' },
  initials: { fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: 16, letterSpacing: 'var(--tr-wider)', textTransform: 'uppercase' },
  rar: { fontFamily: 'var(--font-display)', fontSize: 9, letterSpacing: 'var(--tr-widest)', textTransform: 'uppercase', fontWeight: 700 },
  name: { fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 13, letterSpacing: 'var(--tr-wider)', textTransform: 'uppercase', color: 'var(--fg)' },
  team: { fontFamily: 'var(--font-body)', fontSize: 11, color: 'var(--fg-dim)' },
  pts: { fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: 18 },
  rarity: {
    common:    { c: 'var(--k-rarity-common)',    art: { background: 'linear-gradient(180deg,#2a2a32,#14141a)', border: '1px solid var(--k-rarity-common)', color: 'var(--k-rarity-common)' } },
    rare:      { c: 'var(--k-rarity-rare)',      art: { background: 'linear-gradient(180deg,#0f1e2e,#08101a)', border: '1px solid var(--k-rarity-rare)', color: 'var(--k-rarity-rare)', boxShadow: 'var(--sh-glow-rare)' } },
    epic:      { c: 'var(--k-rarity-epic)',      art: { background: 'linear-gradient(180deg,#1a0d2a,#0c0616)', border: '1px solid var(--k-rarity-epic)', color: 'var(--k-rarity-epic)', boxShadow: 'var(--sh-glow-epic)' } },
    legendary: { c: 'var(--k-rarity-legendary)', art: { background: 'linear-gradient(180deg,#2a1a0a,#1a0a04)', border: '1px solid var(--k-rarity-legendary)', color: 'var(--k-rarity-legendary)', boxShadow: 'var(--sh-glow-amber)' } }
  }
};

window.CardSlot = CardSlot;
