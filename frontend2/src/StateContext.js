import { createContext, useContext, useState } from "react";

const StateContext = createContext();

export function StateProvider({ children }) {
  const [state, setState] = useState({});
  const [messages, setMessages] = useState([]);
  const [stateVisible, setStateVisible] = useState(true);
  const [loading, setLoading] = useState(false);

  const updateState = (newState) => {
    setState((prev) => ({
      ...prev,
      ...newState,
      responses: [...(prev.responses || []), ...(newState.responses || [])],
    }));
  };

  return (
    <StateContext.Provider
      value={{
        state,
        updateState,
        messages,
        setMessages,
        stateVisible,
        setStateVisible,
        loading,
        setLoading,
      }}
    >
      {children}
    </StateContext.Provider>
  );
}

export const useAppState = () => useContext(StateContext);
