function Tabs({ tabs, active, onChange }) {
  return (
    <div style={tabStyles.bar}>
      {tabs.map(t => (
        <button key={t} onClick={() => onChange(t)}
          style={{...tabStyles.tab, ...(active === t ? tabStyles.active : {})}}>
          {t}
        </button>
      ))}
    </div>
  );
}

const tabStyles = {
  bar: { display: 'flex', gap: 4, borderBottom: '1px solid var(--border-soft)', padding: '0 28px', background: 'var(--k-ink-950)' },
  tab: { padding: '14px 20px', fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 13, letterSpacing: 'var(--tr-wider)', textTransform: 'uppercase', background: 'none', border: 'none', color: 'var(--fg-muted)', borderBottom: '2px solid transparent', marginBottom: -1, cursor: 'pointer' },
  active: { color: 'var(--accent)', borderBottomColor: 'var(--accent)' }
};

window.Tabs = Tabs;
