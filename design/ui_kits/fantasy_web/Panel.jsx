function Panel({ title, eyebrow, children, right, span }) {
  return (
    <section style={{...panelStyles.root, gridColumn: span ? `span ${span}` : undefined}}>
      <header style={panelStyles.head}>
        <div>
          {eyebrow && <div style={panelStyles.eyebrow}>{eyebrow}</div>}
          {title && <h2 style={panelStyles.title}>{title}</h2>}
        </div>
        {right}
      </header>
      <div style={panelStyles.body}>{children}</div>
    </section>
  );
}

const panelStyles = {
  root: { background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: 20 },
  head: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14, gap: 12 },
  eyebrow: { fontFamily: 'var(--font-display)', fontSize: 10, letterSpacing: 'var(--tr-widest)', textTransform: 'uppercase', color: 'var(--fg-dim)', fontWeight: 700, marginBottom: 4 },
  title: { fontFamily: 'var(--font-display)', fontSize: 20, letterSpacing: 'var(--tr-wider)', textTransform: 'uppercase', fontWeight: 700, color: 'var(--fg)', margin: 0 },
  body: {}
};

function Button({ variant = 'primary', children, icon, ...props }) {
  const base = { fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 13, letterSpacing: 'var(--tr-wider)', textTransform: 'uppercase', padding: '10px 18px', border: 'none', cursor: 'pointer', borderRadius: 4, display: 'inline-flex', alignItems: 'center', gap: 8 };
  const variants = {
    primary:   { background: 'var(--accent)', color: '#fff' },
    secondary: { background: 'var(--bg-card-hi)', color: 'var(--fg)', border: '1px solid var(--border)' },
    ghost:     { background: 'transparent', color: 'var(--fg-muted)', border: '1px solid var(--border)' },
    twitch:    { background: 'var(--k-twitch)', color: '#fff' },
    danger:    { background: 'var(--k-err)', color: '#fff' }
  };
  return <button {...props} style={{...base, ...variants[variant], ...(props.style||{})}}>{icon && <i data-lucide={icon} width="14" height="14"></i>}{children}</button>;
}

window.Panel = Panel;
window.Button = Button;
