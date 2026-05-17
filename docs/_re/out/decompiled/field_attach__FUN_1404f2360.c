// FUN_1404f2360 @ 0x1404f2360
// purpose-guess: field_attach
// callers (132):
//   FUN_140354c00 @ 140354c00
//   FUN_1403579f0 @ 1403579f0
//   FUN_140428290 @ 140428290
//   FUN_140448680 @ 140448680
//   FUN_14044b6c0 @ 14044b6c0
//   FUN_14044c330 @ 14044c330
//   FUN_140461f20 @ 140461f20
//   FUN_1404634c0 @ 1404634c0
//   FUN_14046bff0 @ 14046bff0
//   FUN_14046c4a0 @ 14046c4a0
//   FUN_14046cbd0 @ 14046cbd0
//   FUN_140475a90 @ 140475a90
//   FUN_1404764e0 @ 1404764e0
//   FUN_140476f40 @ 140476f40
//   FUN_140477150 @ 140477150
//   FUN_140477560 @ 140477560
//   FUN_140477ef0 @ 140477ef0
//   FUN_14047d3c0 @ 14047d3c0
//   FUN_14047d900 @ 14047d900
//   FUN_140481850 @ 140481850
//   FUN_140485c10 @ 140485c10
//   FUN_14049ae80 @ 14049ae80
//   FUN_14049db40 @ 14049db40
//   FUN_14049de90 @ 14049de90
//   FUN_14049ee50 @ 14049ee50
//   FUN_14049f6e0 @ 14049f6e0
//   FUN_14049f7e0 @ 14049f7e0
//   FUN_14049f950 @ 14049f950
//   FUN_14049fa50 @ 14049fa50
//   FUN_14049fc70 @ 14049fc70
//   FUN_1404a06d0 @ 1404a06d0
//   FUN_1404a66d0 @ 1404a66d0
//   FUN_1404a6bf0 @ 1404a6bf0
//   FUN_1404a71c0 @ 1404a71c0
//   FUN_1404a7420 @ 1404a7420
//   FUN_1404a7510 @ 1404a7510
//   FUN_1404a99c0 @ 1404a99c0
//   FUN_1404a9ab0 @ 1404a9ab0
//   FUN_1404d19a0 @ 1404d19a0
//   FUN_1404d1a60 @ 1404d1a60
//   FUN_1404e3490 @ 1404e3490
//   FUN_1404e6400 @ 1404e6400
//   FUN_1404fa850 @ 1404fa850
//   FUN_1404fac90 @ 1404fac90
//   FUN_1404fafa0 @ 1404fafa0
//   FUN_14055a060 @ 14055a060
//   FUN_140584a60 @ 140584a60
//   FUN_140585090 @ 140585090
//   FUN_140585cc0 @ 140585cc0
//   FUN_1405c0170 @ 1405c0170


void FUN_1404f2360(longlong *param_1,longlong *param_2,undefined4 param_3,undefined8 param_4,
                  undefined8 param_5,longlong param_6)

{
  uint uVar1;
  uint uVar2;
  uint uVar3;
  longlong lVar4;
  uint uVar5;
  char *local_18;
  undefined4 local_10;
  
  *(undefined4 *)(param_2 + 5) = param_3;
  (**(code **)(*param_2 + 0x10))(param_2,param_4);
  if (*PTR_DAT_1412c7ab0 != '\0') {
    FUN_140511120(param_2 + 10,&PTR_DAT_1412c7ab0);
  }
  FUN_140511120(param_2 + 0xc,&PTR_DAT_1412c7aa0);
  param_2[0x14] = param_6;
  (**(code **)(*param_2 + 0x20))(param_2,param_1);
  if ((int)param_2[5] == 0) {
    *(int *)(param_2 + 5) = DAT_1412c05b4;
    DAT_1412c05b4 = DAT_1412c05b4 + -1;
  }
  if (*PTR_DAT_1412c8b30 == '\0') {
    if ((*(char *)param_2[1] == '\0') && (DAT_140eb46d0 == '\0')) {
      local_18 = "<unnamed meta member>";
      local_10 = 0x80000015;
      (**(code **)(*param_2 + 0x10))(param_2,&local_18);
    }
  }
  else {
    (**(code **)(*param_2 + 0x10))(param_2,&PTR_DAT_1412c8b30);
  }
  lVar4 = param_1[0x11];
  param_2[0xe] = *(longlong *)(lVar4 + 0x28);
  *(longlong **)(lVar4 + 0x28) = param_2 + 0xe;
  lVar4 = (**(code **)(*param_1 + 0x70))(param_1);
  param_2[0xf] = lVar4;
  lVar4 = param_1[0x11];
  uVar1 = *(uint *)(lVar4 + 0x10);
  uVar2 = *(uint *)(lVar4 + 0x14);
  uVar5 = uVar1 + 1;
  if (uVar2 < uVar5) {
    uVar3 = 8;
    if (8 < uVar2) {
      uVar3 = uVar2;
    }
    for (; uVar3 < uVar5; uVar3 = uVar3 * 2) {
    }
    FUN_140153520(lVar4 + 8);
  }
  *(uint *)(lVar4 + 0x10) = uVar5;
  *(longlong **)(*(longlong *)(lVar4 + 8) + (ulonglong)uVar1 * 8) = param_2;
  return;
}

