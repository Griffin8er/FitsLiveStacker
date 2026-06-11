import { useEffect, useRef, useState } from "react";
import fitsIcon from "./assets/fits.svg";
import "./App.css";

const API_URL = "http://127.0.0.1:8000";

function App() {
  const [directory, setDirectory] = useState("");
  const [status, setStatus] = useState("");
  const [stackProgress, setStackProgress] = useState(null);
  const [stackedImageUrl, setStackedImageUrl] = useState("");

  const pollingRef = useRef(null);
  const imageVersionRef = useRef(-1);

  async function chooseFolder() {
    try {
      const folder = await window.electronAPI.selectFolder();

      if (!folder) return;

      setDirectory(folder);

      const response = await fetch(`${API_URL}/set-directory`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ path: folder }),
      });

      const data = await response.json();
      setStatus(JSON.stringify(data, null, 2));
    } catch (error) {
      setStatus(`Choose folder error: ${error.message}`);
    }
  }

  async function getStatus() {
    try {
      const response = await fetch(`${API_URL}/status`);
      const data = await response.json();
      setStatus(JSON.stringify(data, null, 2));
    } catch (error) {
      setStatus(`Status error: ${error.message}`);
    }
  }

  function startPolling() {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }

    pollingRef.current = setInterval(async () => {
      try {
        const response = await fetch(`${API_URL}/stack-progress?t=${Date.now()}`);
        const data = await response.json();

        setStackProgress(data);

        if (
          data.output &&
          data.image_version !== undefined &&
          data.image_version !== imageVersionRef.current
        ) {
          imageVersionRef.current = data.image_version;
          setStackedImageUrl(`${API_URL}/stacked-image?t=${Date.now()}`);
        }

        if (data.error) {
          setStatus(JSON.stringify(data, null, 2));
        }
      } catch (error) {
        setStatus(`Polling error: ${error.message}`);
      }
    }, 500);
  }

  async function startWatching() {
    try {
      imageVersionRef.current = -1;
      setStackedImageUrl("");

      setStackProgress({
        running: true,
        watching: true,
        current: 0,
        total: 0,
        done: false,
        error: null,
        output: null,
        last_file: null,
        image_version: 0,
      });

      const response = await fetch(`${API_URL}/start-watch-stack`, {
        method: "POST",
      });

      const data = await response.json();
      setStatus(JSON.stringify(data, null, 2));

      if (data.success) {
        startPolling();
      } else {
        setStackProgress({
          running: false,
          watching: false,
          current: 0,
          total: 0,
          done: false,
          error: data.error,
          output: null,
          last_file: null,
          image_version: 0,
        });
      }
    } catch (error) {
      setStatus(`Start error: ${error.message}`);
    }
  }

  async function stopWatching() {
    try {
      const response = await fetch(`${API_URL}/stop-watch-stack`, {
        method: "POST",
      });

      const data = await response.json();
      setStatus(JSON.stringify(data, null, 2));

      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }

      const progressResponse = await fetch(`${API_URL}/stack-progress`);
      const progressData = await progressResponse.json();
      setStackProgress(progressData);
    } catch (error) {
      setStatus(`Stop error: ${error.message}`);
    }
  }

  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  const current = stackProgress?.current || 0;
  const total = stackProgress?.total || 0;

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header__title">
          <img src={fitsIcon} alt="FitsLiveStacker logo" className="header-icon" />
          <h1>FitsLiveStacker</h1>
        </div>
      </header>

      <div className="card">
        <h2>Watch Directory</h2>

        <input value={directory} readOnly placeholder="No folder selected" />

        <div className="buttons">
          <button onClick={chooseFolder}>Choose Folder</button>
          <button onClick={startWatching}>Start Live Stack</button>
          <button onClick={stopWatching}>Stop Live Stack</button>
        </div>
      </div>

      <div className="card">
        <h2>Stack Progress</h2>

        {stackProgress ? (
          <>
            <p>
              {stackProgress.watching
                ? `Watching folder — stacked ${current} files`
                : "Not watching"}
            </p>
            
            <progress value={current} max={total || 1} style={{ width: "100%" }} />

            {stackProgress.last_file && (
              <p>Last file: {stackProgress.last_file}</p>
            )}

            {stackProgress.error && (
              <p style={{ color: "red" }}>{stackProgress.error}</p>
            )}
          </>
        ) : (
          <p>No live stack started yet.</p>
        )}
      </div>

      <div className="card">
        <h2>Current Stack</h2>

        {stackedImageUrl ? (
          <img
            src={stackedImageUrl}
            alt="Current stacked result"
            className="preview"
          />
        ) : (
          <p>No stacked image yet.</p>
        )}
      </div>
    </div>
  );
}

export default App;
