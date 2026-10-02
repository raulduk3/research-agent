import { useApi } from "../api/context.tsx";
import { ChatPanel } from "../components/ChatPanel.tsx";
import { Tree } from "../components/Tree.tsx";

/** Chat beside the tree: ask the island's swarm, then follow an answer down to the paper, the run and its steps. */
export function ChatPage() {
  const island = useApi().session?.island ?? null;
  return (
    <div className="chatlay">
      <section className="main">
        <h1>chat with the swarm</h1>
        <p className="lead">Answers come from what the swarm has stored and link into the tree.</p>
        <ChatPanel />
      </section>
      <section className="side">
        <div className="sec">
          <h2>tree</h2>
          <span>cost at every level</span>
        </div>
        {island !== null && <Tree islandId={island} />}
      </section>
    </div>
  );
}
