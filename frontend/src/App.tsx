import { useEffect, useState } from 'react';
import { Activity, ShieldAlert, IndianRupee, ShieldCheck, Clock } from 'lucide-react';
import './index.css';

// Types matching the FastAPI response
interface DashboardStats {
  active_cases: number;
  recovered_amount_inr: number;
  recovered_cases: number;
  escalated_cases: number;
  awaiting_approval: number;
}

interface CaseItem {
  case_ref: string;
  status: string;
  risk_band: string | null;
  risk_score: number;
  diagnosis: string | null;
  strategy: string;
  retry_count: number;
  outcome: string | null;
  created_at: string;
}

function App() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [loading, setLoading] = useState(true);

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  const fetchData = async () => {
    try {
      const [statsRes, casesRes] = await Promise.all([
        fetch(`${API_URL}/api/dashboard`),
        fetch(`${API_URL}/api/cases?limit=15`)
      ]);
      
      if (statsRes.ok) setStats(await statsRes.json());
      if (casesRes.ok) setCases(await casesRes.json());
    } catch (error) {
      console.error("Error fetching data:", error);
    } finally {
      setLoading(false);
    }
  };

  // Poll every 2 seconds for the live ticker effect
  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 2000);
    return () => clearInterval(interval);
  }, []);

  if (loading && !stats) {
    return <div className="loading">Initializing Secure Connection...</div>;
  }

  const safeStats = stats || {
    recovered_amount_inr: 0,
    active_cases: 0,
    escalated_cases: 0
  };

  return (
    <div className="app-container">
      <header>
        <div className="logo-group">
          <ShieldCheck className="logo-icon" size={32} />
          <h1>Recoup</h1>
        </div>
        <div className={`status-badge ${!stats ? 'offline' : ''}`} style={!stats ? {color: 'var(--accent-red)', background: 'var(--accent-red-glow)', borderColor: 'rgba(239, 68, 68, 0.3)'} : {}}>
          <div className="pulse" style={!stats ? {backgroundColor: 'var(--accent-red)'} : {}}></div>
          {stats ? 'Live Connection' : 'Backend Offline (Run make dev)'}
        </div>
      </header>

      {/* Hero Stats */}
      <section className="stats-grid">
        <div className="stat-card">
          <div className="stat-title">
            <IndianRupee size={16} />
            Recovered Revenue
          </div>
          <div className="stat-value green">
            ₹{safeStats.recovered_amount_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
        </div>

        <div className="stat-card blue">
          <div className="stat-title">
            <Activity size={16} />
            Active Cases
          </div>
          <div className="stat-value blue">
            {safeStats.active_cases}
          </div>
        </div>

        <div className="stat-card red">
          <div className="stat-title">
            <ShieldAlert size={16} />
            Human Escalations
          </div>
          <div className="stat-value red">
            {safeStats.escalated_cases}
          </div>
        </div>
      </section>

      {/* Recent Cases Table */}
      <section>
        <div className="section-title">
          <Clock size={20} />
          Recent Recovery Cases
        </div>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Case Ref</th>
                <th>Status</th>
                <th>Diagnosis</th>
                <th>Strategy</th>
                <th>Risk Band</th>
                <th>Retries</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.case_ref}>
                  <td className="case-ref">{c.case_ref}</td>
                  <td>
                    <span className={`badge ${c.status}`}>
                      {c.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="diagnosis" title={c.diagnosis || 'Pending'}>
                    {c.diagnosis || 'Pending Analysis...'}
                  </td>
                  <td>{c.strategy}</td>
                  <td>{c.risk_band || '-'}</td>
                  <td>{c.retry_count}/3</td>
                </tr>
              ))}
              {cases.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                    {!stats ? 'Cannot connect to backend API (http://localhost:8000)...' : 'Waiting for webhook events...'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default App;
