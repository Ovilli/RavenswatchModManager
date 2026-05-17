// caller of text_localizer
// target: 0x14055d850
// caller fn: FUN_14055d970 @ 0x14055d970


longlong * FUN_14055d970(longlong param_1)

{
  code *pcVar1;
  char *pcVar2;
  longlong *plVar3;
  undefined8 *puVar4;
  longlong lVar5;
  longlong *plVar6;
  longlong local_28;
  uint local_20;
  int local_1c;
  char *local_18;
  uint local_10;
  
  plVar3 = (longlong *)FUN_140556060();
  pcVar1 = *(code **)(*plVar3 + 0x60);
  puVar4 = (undefined8 *)FUN_14055d850(param_1,&local_28);
  pcVar2 = (char *)*puVar4;
  local_18 = "";
  if (*pcVar2 != '\0') {
    local_18 = pcVar2;
  }
  lVar5 = -1;
  do {
    lVar5 = lVar5 + 1;
  } while (pcVar2[lVar5] != '\0');
  local_10 = ((uint)lVar5 ^ *(uint *)(puVar4 + 1)) & 0x7fffffff ^ *(uint *)(puVar4 + 1);
  (*pcVar1)(plVar3,&local_18);
  if (((local_1c != 0) && ((local_20 & 0x80000000) == 0)) && (local_28 != 0)) {
    LOCK();
    DAT_14143ea74 = DAT_14143ea74 + 1;
    UNLOCK();
    thunk_FUN_140cbe5f0();
  }
  *(undefined1 *)((longlong)plVar3 + 0x317) = 0;
  *(byte *)((longlong)plVar3 + 0x234) = *(byte *)((longlong)plVar3 + 0x234) & 0xbf;
  lVar5 = FUN_140559f10(param_1);
  if (lVar5 == 0) {
    lVar5 = param_1 + 0x128;
  }
  (**(code **)(*plVar3 + 0xd8))(plVar3,lVar5 + 0x50);
  plVar6 = (longlong *)(lVar5 + 0x48);
  if (*plVar6 == 0) {
    plVar6 = (longlong *)(DAT_14140dde8 + 0x50);
  }
  FUN_140538480(plVar3,plVar6);
  *(undefined4 *)(plVar3 + 0x4d) = *(undefined4 *)(param_1 + 0x18);
  *(byte *)((longlong)plVar3 + 0x234) = *(byte *)((longlong)plVar3 + 0x234) & 0xfb;
  *(byte *)((longlong)plVar3 + 0x235) = *(byte *)((longlong)plVar3 + 0x235) & 0xfe;
  *(undefined4 *)((longlong)plVar3 + 0x324) = *(undefined4 *)(lVar5 + 0x70);
  *(undefined4 *)((longlong)plVar3 + 0x31c) = *(undefined4 *)(lVar5 + 0x68);
  *(undefined4 *)(plVar3 + 100) = *(undefined4 *)(lVar5 + 0x6c);
  return plVar3;
}

