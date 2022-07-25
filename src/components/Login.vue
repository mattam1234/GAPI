<template>
    <div>
        <p>Joining an session? please enter a session id and Steam id.</p>
        <div class="form-group">
        <input type="text"
           id="SesionId"
           class="form-control"
           v-model="userData.SesionId">
           </div>
           <div class="form-group">
        <input type="text"
            id="Steamid"
            class="form-control"
            v-model="userData.SteamId"/>
        <button type="submit">Submit</button>
        </div>
    </div>
</template>

<script lang="ts">
    export default {
        data() {
            return {
                userData: {
                    SesionId: '',
                    SteamId: ''
                }
            }
        }
    }
</script>




