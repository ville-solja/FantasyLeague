function MatchupRow({ div = 1, home, away, scoreH = "—", scoreA = "—", meta = "", past = false }) {
  return (
    <div style={{...mrStyles.row, opacity: past ? 0.45 : 1}}>
      <span style={{...mrStyles.div, ...(div === 1 ? mrStyles.div1 : mrStyles.div2)}}>Div {div}</span>
      <span style={mrStyles.team}>{home}</span>
      <span style={mrStyles.score}>{scoreH}<span style={mrStyles.vs}>VS.</span>{scoreA}</span>
      <span style={{...mrStyles.team, textAlign:'right'}}>{away}</span>
      <span style={mrStyles.meta}>{meta}</span>
    </div>
  );
}
const mrStyles = {
  row: { display: 'grid', gridTemplateColumns: '64px 1fr 88px 1fr 140px', alignItems: 'center', gap: 14, padding: '11px 14px', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)' },
  div: { fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 10, letterSpacing: 'var(--tr-widest)', textTransform: 'uppercase', padding: '3px 6px', borderRadius: 2, textAlign: 'center' },
  div1: { background: '#1a1a2a', color: '#7a7aca', border: '1px solid #3a3a6a' },
  div2: { background: '#1a2a1a', color: '#7aca7a', border: '1px solid #3a6a3a' },
  team: { fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 15, letterSpacing: 'var(--tr-wider)', textTransform: 'uppercase', color: 'var(--fg)' },
  score: { fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: 20, textAlign: 'center', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, color: 'var(--fg)' },
  vs: { fontFamily: 'var(--font-display)', fontWeight: 900, fontSize: 11, color: 'var(--accent)', letterSpacing: 'var(--tr-wider)' },
  meta: { fontFamily: 'var(--font-body)', fontSize: 12, color: 'var(--fg-dim)', textAlign: 'right' }
};

function LeaderboardTable({ rows }) {
  return (
    <table style={{width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-body)', fontSize: 13}}>
      <thead>
        <tr>
          {["Rank","User","Season","Last wk"].map((h,i) => (
            <th key={h} style={{fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 10, letterSpacing: 'var(--tr-widest)', textTransform: 'uppercase', textAlign: i>1?'right':'left', padding: '8px 10px', borderBottom: '1px solid var(--border)', color: 'var(--fg-dim)'}}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r,i) => (
          <tr key={r.user}>
            <td style={{padding: '9px 10px', borderBottom: '1px solid var(--border-soft)', fontFamily: 'var(--font-display)', fontWeight: 900, color: 'var(--accent)'}}>{String(i+1).padStart(2,'0')}</td>
            <td style={{padding: '9px 10px', borderBottom: '1px solid var(--border-soft)', color: 'var(--fg)'}}>{r.user}</td>
            <td style={{padding: '9px 10px', borderBottom: '1px solid var(--border-soft)', fontFamily: 'var(--font-display)', fontWeight: 700, fontVariantNumeric: 'tabular-nums', textAlign: 'right'}}>{r.season}</td>
            <td style={{padding: '9px 10px', borderBottom: '1px solid var(--border-soft)', fontFamily: 'var(--font-display)', fontWeight: 700, fontVariantNumeric: 'tabular-nums', textAlign: 'right', color: 'var(--k-ok)'}}>+{r.last}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

window.MatchupRow = MatchupRow;
window.LeaderboardTable = LeaderboardTable;
