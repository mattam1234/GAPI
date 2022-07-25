import { defineStore } from "pinia";

export const Session = defineStore({
    id: "Session",
    state: () => ({
      sessionId: "",
      users: [],
    }),
    actions: {
        setUser() {
            // todo implement user setter
            return;
        }
        setSessionId(){
            this.sessionId = 
        }
    }
  });
  